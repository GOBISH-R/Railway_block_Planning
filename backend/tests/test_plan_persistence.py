"""Plans survive a restart.

The claim: a plan id handed to a controller keeps working after the process
that produced it is gone. Everything here exists to test that, and the central
assertion is literal dict equality between the response a live solve returned
and the response reconstructed from PostgreSQL -- not a field-by-field check,
which would pass while quietly dropping a key.

Split as usual. The tests above the divider need no database and cover the part
that decides whether anything is written at all; the rest skip without one.

Two things deliberately NOT asserted here, because they are not true and should
not become true by accident:

  * A restored plan carries no PlanInternals. Explaining a block needs 16,746
    columns and 11,648 windows, which are not written per plan, so a Why
    request against a restored plan answers 409 -- exactly as it does for a
    plan whose internals were evicted in a long-running process. Re-POSTing
    the same request recovers it. That whole sequence is asserted below rather
    than assumed; an earlier draft of this module claimed the Why request
    recomputed them by itself, and driving the real API showed it does not.
  * A restored plan is not marked cache_hit. It was read from disk, not served
    from the in-memory cache, and saying otherwise would misreport
    stage_timings_s as this request's latency.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from blockplan_service import PlanningContext, PlanRequest, PlanningService, paths
from blockplan_service.persistence import (
    FROZEN_SNAPSHOT_ID,
    NullPlanStore,
    PersistenceError,
    PlanStore,
    RawPlanValues,
    resolve,
    snapshot_id_for,
)
from blockplan_service.planner import (
    COST_DP,
    RELIABILITY_DP,
    raw_plan_values,
)

from test_reference_plan import REFERENCE_PLAN_ID, REFERENCE_REQUEST

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Whether anything is written -- no database needed
# ---------------------------------------------------------------------------

def test_persistence_is_off_by_default():
    """Startup must not require PostgreSQL. Silence means memory only."""
    store = resolve({})
    assert isinstance(store, NullPlanStore)
    assert store.enabled is False


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_the_off_spellings_all_mean_off(value):
    assert resolve({"BLOCKPLAN_PERSIST_PLANS": value}).enabled is False


def test_asking_for_persistence_without_a_database_is_refused():
    """Not a silent fallback to memory. Someone who asks for durable plans and
    does not get them finds out at the worst possible moment."""
    with pytest.raises(PersistenceError) as exc:
        resolve({"BLOCKPLAN_PERSIST_PLANS": "1"})
    assert "no database is configured" in str(exc.value)


def test_a_nonsense_value_is_refused():
    with pytest.raises(PersistenceError):
        resolve({"BLOCKPLAN_PERSIST_PLANS": "maybe"})


def test_the_null_store_is_inert_but_complete():
    """The service calls the store unconditionally, so every method must exist
    and be harmless rather than raise."""
    store = NullPlanStore()
    assert isinstance(store, PlanStore)
    store.save_plan({"plan_id": "x"}, snapshot_id=1,
                    raw=RawPlanValues(0.0, {}))
    store.record_approval("x", "B0001", "APPROVED", snapshot_id=1)
    assert store.load_plan("x", snapshot_id=1) is None
    assert store.recent_plans(10, snapshot_id=1) == []
    assert store.plan_ids(snapshot_id=1) == ()
    assert store.approvals_for("x", snapshot_id=1) == []
    assert "not persisted" in store.describe()


def test_a_service_with_no_store_still_answers_everything(service):
    assert service.store.enabled is False
    assert service.restore_plans() == 0
    assert service.stored_plan("nope") is None


# -- which snapshot a plan belongs to ---------------------------------------

def test_a_plan_from_the_frozen_tree_is_snapshot_one(csv_context):
    """blockplan_db.loader defines snapshot 1 as exactly these files, and
    Phase 3 measured the round trip as identical, so the attribution is true."""
    assert csv_context.tree == paths.FROZEN_TREE
    assert snapshot_id_for(csv_context) == FROZEN_SNAPSHOT_ID


def test_a_plan_from_an_unattributable_tree_is_refused(tmp_path):
    """A copy, a temp directory, an experiment. Recording snapshot 1 against
    one of those would put a false provenance claim in the audit trail."""

    class _Ctx:
        tree = paths.DatasetTree(str(tmp_path))
        snapshot_id = None

    with pytest.raises(PersistenceError) as exc:
        snapshot_id_for(_Ctx())
    assert str(tmp_path) in str(exc.value)


def test_a_declared_snapshot_wins():
    class _Ctx:
        tree = paths.DatasetTree("/wherever")
        snapshot_id = 7

    assert snapshot_id_for(_Ctx()) == 7


def test_a_csv_context_declares_no_snapshot_of_its_own(csv_context):
    """Files, not a snapshot row. Turning that None into 1 is a provenance
    claim, and it is made in snapshot_id_for() where it can be refused."""
    assert csv_context.snapshot_id is None


# ---------------------------------------------------------------------------
# Live database
# ---------------------------------------------------------------------------

from blockplan_db.connection import is_configured  # noqa: E402

requires_db = pytest.mark.skipif(
    not is_configured(), reason="no database configured (BLOCKPLAN_DATABASE_URL / PG*)"
)


@pytest.fixture(scope="module")
def store():
    from blockplan_db.plan_store import PostgresPlanStore

    return PostgresPlanStore()


@pytest.fixture(scope="module")
def saved(context: PlanningContext, service: PlanningService, store):
    """One real solve, persisted. Yields (live payload, internals).

    Reuses the session context and window cache -- window generation is ~13.5 s
    and is not what this file is testing -- but takes its own PlanningService
    so the plan is genuinely written through the store rather than injected.
    """
    planning = PlanningService(context=context, window_cache=service.windows,
                               store=store)
    payload = planning.plan(REFERENCE_REQUEST, use_cache=False)
    internals = planning.internals(payload["plan_id"])
    yield payload, internals
    with __import__("blockplan_db.connection", fromlist=["connect"]).connect() as c:
        c.execute("DELETE FROM plans WHERE plan_id = %s", (payload["plan_id"],))
        c.commit()


# -- save -> restart -> retrieve --------------------------------------------

@requires_db
@pytest.mark.slow
def test_a_restored_plan_is_identical_to_the_response_that_was_saved(saved, store):
    """The whole point, as one assertion.

    Equality of the entire dict: every key, every block, every rounded figure,
    the summary, the instance sizes and the stage timings. A reconstruction that
    dropped a field or re-rounded differently fails here.
    """
    payload, _ = saved
    restored = store.load_plan(payload["plan_id"], snapshot_id=FROZEN_SNAPSHOT_ID)
    assert restored == payload


@requires_db
@pytest.mark.slow
def test_a_fresh_service_serves_a_plan_it_never_computed(saved, context, store):
    """Restart, simulated where it actually matters: the in-memory plan cache
    is what dies with the process, so a new PlanningService with an empty cache
    is the condition under test."""
    payload, _ = saved
    after_restart = PlanningService(context=context, store=store)

    assert after_restart.cached_plan(payload["plan_id"]) is None, "cache not empty"
    assert after_restart.stored_plan(payload["plan_id"]) == payload


@requires_db
@pytest.mark.slow
def test_a_retrieved_plan_is_kept_in_memory_for_next_time(saved, context, store):
    payload, _ = saved
    after_restart = PlanningService(context=context, store=store)
    after_restart.stored_plan(payload["plan_id"])
    assert after_restart.cached_plan(payload["plan_id"]) == payload


@requires_db
@pytest.mark.slow
def test_startup_restores_plans_without_being_asked_for_one(saved, context, store):
    payload, _ = saved
    after_restart = PlanningService(context=context, store=store)

    assert after_restart.restore_plans() >= 1
    assert payload["plan_id"] in after_restart.cached_plan_ids


@requires_db
@pytest.mark.slow
def test_a_computed_plan_is_never_overwritten_by_a_restored_one(saved, context, store):
    """Whatever this process computed is newer than anything it reads back."""
    payload, _ = saved
    planning = PlanningService(context=context, store=store)
    marker = dict(payload, status="MARKER")
    planning._plans[payload["plan_id"]] = marker

    planning.restore_plans()
    assert planning.cached_plan(payload["plan_id"])["status"] == "MARKER"


@requires_db
@pytest.mark.slow
def test_the_plan_survives_a_real_process_restart(saved):
    """The literal claim, tested literally: a separate Python process, a fresh
    FastAPI app, and GET /plan/{id} for an id it has never seen."""
    payload, _ = saved
    script = (
        "import json, sys;"
        "sys.path.insert(0, r'" + BACKEND_DIR + "');"
        "from fastapi.testclient import TestClient;"
        "from blockplan_api.app import app;"
        "c = TestClient(app);"
        "c.__enter__();"
        "r = c.get('/plan/" + payload["plan_id"] + "');"
        "print(json.dumps({'code': r.status_code, 'body': r.json()}))"
    )
    env = dict(os.environ, BLOCKPLAN_PERSIST_PLANS="1", BLOCKPLAN_WARM_ON_STARTUP="0")
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, cwd=BACKEND_DIR, env=env)
    assert proc.returncode == 0, proc.stderr[-3000:]

    import json

    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["code"] == 200
    assert result["body"] == payload


@requires_db
@pytest.mark.slow
def test_explaining_a_restored_plan_needs_a_re_plan_first(saved, context, store):
    """What a restored plan can and cannot do, stated exactly.

    Internals are not persisted, so a restored plan is in the same position as
    one whose internals were evicted: the Why request answers 409 and says to
    re-run the plan. Re-POSTing the identical request produces the same plan id,
    falls through the cache check because internals are missing, recomputes
    them, and the Why request then succeeds.

    This is here because the first version of this work asserted the Why request
    recovered on its own. Driving the real API showed a 409, so the behaviour is
    pinned rather than described.
    """
    from blockplan_service.explain import (
        ExplanationService,
        ExplanationUnavailableError,
    )

    payload, _ = saved
    after_restart = PlanningService(context=context, store=store)
    after_restart.restore_plans()
    explaining = ExplanationService(after_restart)
    block_id = payload["blocks"][0]["block_id"]

    with pytest.raises(ExplanationUnavailableError) as exc:
        explaining.explain_block(payload["plan_id"], block_id)
    assert "re-run the plan" in str(exc.value)

    replanned = after_restart.plan(REFERENCE_REQUEST)
    assert replanned["plan_id"] == payload["plan_id"]
    assert replanned["cache_hit"] is False, "it must not serve the restored copy"

    explanation = explaining.explain_block(payload["plan_id"], block_id)
    assert explanation["block_id"] == block_id


# -- what exactly was stored ------------------------------------------------

@requires_db
@pytest.mark.slow
def test_the_unrounded_values_are_what_went_in(saved, store):
    """The response rounds; the database must not.

    Compared by repr() against the solver's own objects -- the same form
    test_reference_plan.py's block fingerprint uses -- so a value that was
    rounded, re-parsed or passed through a NUMERIC on the way fails here even
    though the displayed plan would look right.
    """
    payload, internals = saved
    raw = raw_plan_values(internals)

    from blockplan_db.connection import connect

    with connect() as conn:
        objective, = conn.execute(
            "SELECT objective FROM plans WHERE plan_id = %s",
            (payload["plan_id"],)).fetchone()
        rows = conn.execute(
            "SELECT block_id, reliability, traffic_cost, exp_overrun_cost "
            "FROM plan_blocks WHERE plan_id = %s", (payload["plan_id"],)).fetchall()

    assert repr(objective) == repr(raw.objective)
    assert len(rows) == len(payload["blocks"])
    for block_id, reliability, traffic, overrun in rows:
        assert (repr(reliability), repr(traffic), repr(overrun)) == \
            tuple(repr(v) for v in raw.blocks[block_id])


@requires_db
@pytest.mark.slow
def test_the_stored_values_still_round_to_the_displayed_ones(saved, store):
    """Raw storage is only useful if the display is derivable from it."""
    payload, internals = saved
    raw = raw_plan_values(internals)
    for block in payload["blocks"]:
        reliability, traffic, overrun = raw.blocks[block["block_id"]]
        assert round(reliability, RELIABILITY_DP) == block["reliability"]
        assert round(traffic, COST_DP) == block["traffic_cost"]
        assert round(overrun, COST_DP) == block["exp_overrun_cost"]


@requires_db
@pytest.mark.slow
def test_block_order_is_preserved(saved, store):
    payload, _ = saved
    restored = store.load_plan(payload["plan_id"], snapshot_id=FROZEN_SNAPSHOT_ID)
    ids = [b["block_id"] for b in restored["blocks"]]
    assert ids == [b["block_id"] for b in payload["blocks"]]
    assert ids == [f"B{n:04d}" for n in range(1, len(ids) + 1)]


@requires_db
@pytest.mark.slow
def test_deferred_jobs_keep_the_order_the_solver_returned(saved, store):
    """plan_deferred carries seq for this. There is no padded id to recover the
    order from, and the response reproduces the list positionally."""
    payload, _ = saved
    restored = store.load_plan(payload["plan_id"], snapshot_id=FROZEN_SNAPSHOT_ID)
    assert restored["deferred"] == payload["deferred"]


@requires_db
@pytest.mark.slow
def test_the_plan_records_the_dataset_it_was_computed_from(saved, store):
    payload, _ = saved
    assert store.snapshots_holding(payload["plan_id"]) == (FROZEN_SNAPSHOT_ID,)


@requires_db
@pytest.mark.slow
def test_saving_the_same_plan_twice_replaces_rather_than_duplicates(saved, store):
    """The plan id is the request hash, so re-solving the same request is the
    normal way to arrive here twice."""
    payload, internals = saved
    store.save_plan(payload, snapshot_id=FROZEN_SNAPSHOT_ID,
                    raw=raw_plan_values(internals))
    store.save_plan(payload, snapshot_id=FROZEN_SNAPSHOT_ID,
                    raw=raw_plan_values(internals))

    from blockplan_db.connection import connect

    with connect() as conn:
        plans, = conn.execute("SELECT count(*) FROM plans WHERE plan_id = %s",
                              (payload["plan_id"],)).fetchone()
        blocks, = conn.execute(
            "SELECT count(*) FROM plan_blocks WHERE plan_id = %s",
            (payload["plan_id"],)).fetchone()
    assert plans == 1
    assert blocks == len(payload["blocks"])
    assert store.load_plan(payload["plan_id"],
                           snapshot_id=FROZEN_SNAPSHOT_ID) == payload


@requires_db
@pytest.mark.slow
def test_the_reference_plan_id_is_the_one_that_was_stored(saved):
    """Ties this file to the pinned plan, so a change of request defaults that
    moved the id would be caught here too."""
    payload, _ = saved
    assert payload["plan_id"] == REFERENCE_PLAN_ID


# -- approvals ---------------------------------------------------------------

@requires_db
@pytest.mark.slow
def test_approvals_are_recorded_against_a_plan(saved, store):
    """The persistence layer for the approvals table.

    There is no approvals endpoint and no UI: this phase builds the store the
    schema already describes, and wiring a controller decision through the API
    is a separate, product-level decision that has not been made.
    """
    payload, _ = saved
    plan_id = payload["plan_id"]
    first, second = payload["blocks"][0]["block_id"], payload["blocks"][1]["block_id"]

    store.record_approval(plan_id, first, "APPROVED",
                          snapshot_id=FROZEN_SNAPSHOT_ID, decided_by="controller-1")
    store.record_approval(plan_id, second, "REJECTED",
                          snapshot_id=FROZEN_SNAPSHOT_ID, decided_by="controller-1",
                          note="engineering block clashes with a special")

    recorded = store.approvals_for(plan_id, snapshot_id=FROZEN_SNAPSHOT_ID)
    assert [(a["block_id"], a["decision"]) for a in recorded] == [
        (first, "APPROVED"), (second, "REJECTED")]
    assert recorded[1]["note"].startswith("engineering block")
    assert all(a["decided_at"] is not None for a in recorded)


@requires_db
@pytest.mark.slow
def test_a_reversed_decision_is_appended_not_overwritten(saved, store):
    """The table is an audit trail. A controller changing their mind is itself
    a fact worth keeping."""
    payload, _ = saved
    plan_id = payload["plan_id"]
    block_id = payload["blocks"][2]["block_id"]

    store.record_approval(plan_id, block_id, "APPROVED",
                          snapshot_id=FROZEN_SNAPSHOT_ID, decided_by="controller-1")
    store.record_approval(plan_id, block_id, "REJECTED",
                          snapshot_id=FROZEN_SNAPSHOT_ID, decided_by="controller-2",
                          note="withdrawn after the freight path was added")

    for_block = [a for a in store.approvals_for(plan_id,
                                                snapshot_id=FROZEN_SNAPSHOT_ID)
                 if a["block_id"] == block_id]
    assert [a["decision"] for a in for_block] == ["APPROVED", "REJECTED"]


@requires_db
def test_a_database_backed_context_persists_against_its_own_snapshot():
    """The two switches are independent, so reading from PostgreSQL while
    writing plans to it has to work.

    It did not: a database context reads from a materialised temporary tree,
    which is neither the frozen tree nor -- until PlanningContext grew a
    snapshot_id -- something that could name its own snapshot. snapshot_id_for
    refused it outright.
    """
    from blockplan_service.datasource import DatabaseDataSource

    source = DatabaseDataSource(1)
    try:
        ctx = PlanningContext.load(source)
        assert ctx.tree != paths.FROZEN_TREE, "it is reading a materialised tree"
        assert ctx.snapshot_id == 1
        assert snapshot_id_for(ctx) == 1
    finally:
        source.close()


@requires_db
def test_approvals_for_an_unknown_plan_are_empty_not_an_error(store):
    assert store.approvals_for("nosuchplan", snapshot_id=FROZEN_SNAPSHOT_ID) == []


@requires_db
def test_an_unknown_plan_id_reads_back_as_none(store):
    assert store.load_plan("nosuchplan", snapshot_id=FROZEN_SNAPSHOT_ID) is None
    assert store.snapshots_holding("nosuchplan") == ()
