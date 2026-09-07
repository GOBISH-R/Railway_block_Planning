"""Stale cached plans must recompute rather than stay permanently unexplainable.

_plans is unbounded; _internals is bounded and evicts FIFO. A plan therefore
outlives its artefacts as a matter of course, and before this was fixed the
cache-hit path handed back the stale DTO without ever rebuilding them -- so
every Why request for that plan answered 409 for the life of the process, and
re-planning could not clear it because the identical request produced the same
cache key and hit the same branch.

These tests pin the corrected lifecycle and, most importantly, the property it
rests on: that recomputing reproduces the SAME concrete artefacts, not merely
the same objective. If that ever stops being true, TEST 3 fails and the
recovery path becomes unsafe -- it would explain a different block under the
block id the user clicked.
"""
from __future__ import annotations

import threading

import pytest

from blockplan_service import PlanningContext, PlanRequest, PlanningService, planning_lock
from blockplan_service.explain import ExplanationService, ExplanationUnavailableError
from blockplan_service.planner import UnknownPlanError

SCENARIO = "NORMAL_TRAFFIC"


@pytest.fixture(scope="module")
def isolated(context: PlanningContext, service: PlanningService) -> PlanningService:
    """A service of our own, so filling the artefact cache cannot disturb others.

    Shares the session context and the session window cache -- window generation
    is ~13.5 s per scenario and is not what these tests are about -- but keeps
    its own _plans/_internals. max_internals=2 makes eviction cheap to trigger
    without touching the eviction implementation itself.
    """
    return PlanningService(context=context, window_cache=service.windows,
                           max_internals=2)


def evict_internals_of(svc: PlanningService, plan_id: str, *, theta_base: float) -> None:
    """Push `plan_id` out of the artefact cache using the real FIFO only.

    Distinct thetas give distinct cache keys, so each filler is a genuine plan
    stored through the ordinary path. No eviction internals are called directly.
    """
    offset = 0
    while svc.has_internals(plan_id):
        offset += 1
        assert offset <= svc._max_internals + 2, "FIFO did not evict as expected"
        svc.plan(PlanRequest(scenario=SCENARIO, theta=round(theta_base + offset / 1000, 4)))


def block_signature(internals) -> dict:
    """The artefacts the Why panel reads, raw and unrounded."""
    return {
        bid: (
            col.window.section_id,
            col.window.day,
            col.window.start_min,
            col.window.length,
            col.window.end_min,
            tuple(col.job_ids),
            repr(col.reliability),
            repr(col.exp_overrun_cost),
            repr(col.window.traffic_cost),
        )
        for bid, col in internals.blocks_by_id.items()
    }


# -- TEST 1: an intact cache hit still short-circuits ------------------------

def test_intact_cache_hit_does_not_recompute(isolated: PlanningService):
    request = PlanRequest(scenario=SCENARIO, theta=0.911)
    first = isolated.plan(request)
    assert first["cache_hit"] is False
    assert isolated.has_internals(first["plan_id"])

    second = isolated.plan(request)
    assert second["plan_id"] == first["plan_id"]
    assert second["cache_hit"] is True
    # The existing seam for "no solver ran": a hit preserves the ORIGINAL
    # stage timings verbatim. A quiet recompute would overwrite them.
    assert second["stage_timings_s"] == first["stage_timings_s"]


# -- TEST 2: a stale plan recomputes ----------------------------------------

def test_stale_plan_recomputes_and_restores_internals(isolated: PlanningService):
    request = PlanRequest(scenario=SCENARIO, theta=0.921)
    original = isolated.plan(request)
    plan_id = original["plan_id"]

    evict_internals_of(isolated, plan_id, theta_base=0.921)

    # The state this fix exists for: addressable, but unexplainable.
    assert isolated.cached_plan(plan_id) is not None
    assert isolated.has_internals(plan_id) is False

    recovered = isolated.plan(request)

    assert recovered["plan_id"] == plan_id
    assert recovered["cache_hit"] is False
    assert isolated.has_internals(plan_id) is True


# -- TEST 3: the determinism regression guard (the important one) -----------

def test_recomputed_artefacts_are_concretely_identical(isolated: PlanningService):
    """Recovery must restore the SAME plan, not merely an equally good one.

    The instance is degenerate -- many distinct plans share the optimal
    objective -- so matching aggregates prove nothing. What makes recovery safe
    is that block ids map to the same concrete columns, which is what the Why
    panel reads. This holds because the service pins num_workers=1,
    random_seed=1 and resets the RNG before the only RNG-consuming stage; if any
    of that changes, this test is the one that should fail.
    """
    request = PlanRequest(scenario=SCENARIO, theta=0.931)
    original = isolated.plan(request)
    plan_id = original["plan_id"]
    before = block_signature(isolated.internals(plan_id))
    before_deferred = tuple(isolated.internals(plan_id).deferred_job_ids)
    before_objective = isolated.internals(plan_id).objective
    before_status = isolated.internals(plan_id).status

    evict_internals_of(isolated, plan_id, theta_base=0.931)
    assert isolated.has_internals(plan_id) is False

    isolated.plan(request)
    after_internals = isolated.internals(plan_id)
    after = block_signature(after_internals)

    assert list(after.keys()) == list(before.keys()), "block ids or their order moved"
    assert after == before, "a block id now refers to different concrete work"
    assert tuple(after_internals.deferred_job_ids) == before_deferred
    assert after_internals.objective == before_objective
    assert after_internals.status == before_status

    # Job -> block assignment, stated directly rather than inferred.
    def assignment(sig, deferred):
        out = {jid: bid for bid, v in sig.items() for jid in v[5]}
        out.update({jid: "DEFERRED" for jid in deferred})
        return out

    assert assignment(after, after_internals.deferred_job_ids) == assignment(
        before, before_deferred
    )


# -- TEST 4: the Why panel recovers -----------------------------------------

def test_explanation_recovers_after_eviction(isolated: PlanningService):
    request = PlanRequest(scenario=SCENARIO, theta=0.941)
    original = isolated.plan(request)
    plan_id = original["plan_id"]
    explain = ExplanationService(isolated)

    block_id = original["blocks"][9]["block_id"]  # B0010 in a 140-block plan
    before = explain.explain_block(plan_id, block_id)

    evict_internals_of(isolated, plan_id, theta_base=0.941)
    with pytest.raises(ExplanationUnavailableError):
        explain.explain_block(plan_id, block_id)

    # What the frontend does next: re-request the same plan, then explain again.
    isolated.plan(request)
    after = explain.explain_block(plan_id, block_id)

    assert after["block_id"] == block_id
    for field in ("section_id", "day", "start_min", "end_min", "length", "reliability"):
        assert after[field] == before[field]
    assert [j["job_id"] for j in after["jobs"]] == [j["job_id"] for j in before["jobs"]]


# -- TEST 6: recovery goes through the locked compute path -------------------

def test_stale_recovery_holds_the_planning_lock(isolated: PlanningService):
    """Recovery must run the ordinary locked pipeline, not a side path.

    Proven by holding the lock from another thread: if recovery re-solved
    without it, the call would return while the lock was held elsewhere.
    """
    request = PlanRequest(scenario=SCENARIO, theta=0.951)
    plan_id = isolated.plan(request)["plan_id"]
    evict_internals_of(isolated, plan_id, theta_base=0.951)
    assert isolated.has_internals(plan_id) is False

    released = threading.Event()
    observed: list[bool] = []

    def hold_then_release():
        with planning_lock():
            observed.append(isolated.has_internals(plan_id))
            released.set()

    holder = threading.Thread(target=hold_then_release)
    holder.start()
    released.wait(timeout=30)
    holder.join(timeout=30)

    # The lock is reentrant and released by now; recovery must acquire it.
    assert observed == [False]
    assert planning_lock().acquire(blocking=False)
    planning_lock().release()

    isolated.plan(request)
    assert isolated.has_internals(plan_id) is True


# -- TEST 7 / 8: the surrounding cache policy is unchanged -------------------

def test_internals_eviction_is_still_fifo_and_bounded(isolated: PlanningService):
    """Eviction policy is deliberately untouched by this fix."""
    svc = PlanningService(context=isolated.context, window_cache=isolated.windows,
                          max_internals=2)
    ids = []
    for i in range(3):
        ids.append(svc.plan(PlanRequest(scenario=SCENARIO, theta=0.961 + i / 1000))["plan_id"])

    assert svc.has_internals(ids[0]) is False, "oldest write should evict first"
    assert svc.has_internals(ids[1]) is True
    assert svc.has_internals(ids[2]) is True
    with pytest.raises(UnknownPlanError):
        svc.internals(ids[0])


def test_plans_outlive_their_internals_by_design(isolated: PlanningService):
    """_plans stays unbounded on purpose: the UI holds two plans side by side.

    The fix changes when a cached plan may be REUSED, not how long it is kept.
    GET /plan/{id} must still serve a plan whose artefacts are gone.
    """
    svc = PlanningService(context=isolated.context, window_cache=isolated.windows,
                          max_internals=2)
    ids = []
    for i in range(3):
        ids.append(svc.plan(PlanRequest(scenario=SCENARIO, theta=0.971 + i / 1000))["plan_id"])

    assert svc.has_internals(ids[0]) is False
    assert svc.cached_plan(ids[0]) is not None, "plan must remain addressable"
    assert set(ids).issubset(set(svc.cached_plan_ids))
