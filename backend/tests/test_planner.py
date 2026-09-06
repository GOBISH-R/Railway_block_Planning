"""Planning service: determinism, the lock, error semantics, benchmark match.

These are the three tests the roadmap sets as Phase 1's definition of done:
  1. call it twice with identical parameters -> identical output
  2. call it from two threads with different theta -> both correct and isolated
  3. confirm a produced plan matches the frozen benchmark_results.csv row
plus the error semantics the API contract freezes.
"""
from __future__ import annotations

import csv
import json
import threading
import time

import pytest

from blockplan_service import PlanRequest, PlanningService, UnknownScenarioError, planning_lock
from blockplan_service import paths

BENCHMARK_REQUEST = PlanRequest(
    scenario="NORMAL_TRAFFIC",
    horizon_days=14,
    theta=0.90,
    max_bundle_size=5,
    mc_samples=1500,
)


def _frozen_benchmark_row(scenario: str) -> dict:
    with open(paths.BENCHMARK_RESULTS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["scenario"] == scenario:
                return row
    raise AssertionError(f"{scenario} missing from benchmark_results.csv")


# -- 1. determinism --------------------------------------------------------

def test_identical_requests_produce_identical_plans(service: PlanningService):
    first = service.plan(BENCHMARK_REQUEST, use_cache=False)
    second = service.plan(BENCHMARK_REQUEST, use_cache=False)

    # Timings legitimately vary; everything else must not.
    first.pop("stage_timings_s")
    second.pop("stage_timings_s")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_plan_cache_returns_the_same_plan(service: PlanningService):
    plan = service.plan(BENCHMARK_REQUEST)
    again = service.plan(BENCHMARK_REQUEST)
    assert again["plan_id"] == plan["plan_id"]
    assert service.cached_plan(plan["plan_id"]) is not None


def test_cache_hit_is_flagged_and_a_miss_is_not(service: PlanningService):
    """Phase 8 finding: a cache hit must say so.

    Without this flag, a client (the frontend's summary strip) has no way to
    tell a near-instant cache hit from a fresh multi-second solve, because
    stage_timings_s on a hit is whatever the ORIGINAL computation measured --
    not this request's latency. A unique theta is used so this test cannot be
    accidentally satisfied by another test's cache entry left over from
    earlier in the session (the `service` fixture is session-scoped).
    """
    request = PlanRequest(scenario="NORMAL_TRAFFIC", horizon_days=14, theta=0.87,
                          max_bundle_size=5, mc_samples=1500)
    first = service.plan(request)
    assert first["cache_hit"] is False

    second = service.plan(request)
    assert second["cache_hit"] is True
    assert second["plan_id"] == first["plan_id"]
    # The historical timing is preserved on a hit -- it's evidence, not noise --
    # but it must be the SAME (original) number both times, proving the hit
    # path truly skipped re-solving rather than quietly recomputing it.
    assert second["stage_timings_s"] == first["stage_timings_s"]


def test_cache_key_reflects_every_solve_affecting_parameter():
    base = BENCHMARK_REQUEST.cache_key()
    assert PlanRequest(scenario="PEAK_TRAFFIC").cache_key() != base
    for override in (
        {"theta": 0.95},
        {"horizon_days": 7},
        {"max_bundle_size": 3},
        {"mc_samples": 4000},
        {"seed": 99},
    ):
        fields = {
            "scenario": "NORMAL_TRAFFIC", "horizon_days": 14, "theta": 0.90,
            "max_bundle_size": 5, "mc_samples": 1500,
        }
        fields.update(override)
        assert PlanRequest(**fields).cache_key() != base, (
            f"{override} did not change the cache key"
        )


def test_cached_plan_is_a_copy(service: PlanningService):
    """A caller mutating a returned plan must not corrupt the cache."""
    plan = service.plan(BENCHMARK_REQUEST)
    plan["blocks"].clear()
    assert service.cached_plan(plan["plan_id"])["blocks"], "cache was mutated by caller"


# -- 2. the lock -----------------------------------------------------------

def test_concurrent_plans_with_different_theta_are_isolated(service: PlanningService):
    """The reason the lock exists.

    Two requests with different theta must not interleave through core.py's
    module-level globals. Both results must be internally consistent.
    """
    results: dict[float, dict] = {}
    errors: list[BaseException] = []

    def run(theta: float):
        try:
            results[theta] = service.plan(
                PlanRequest(scenario="NORMAL_TRAFFIC", horizon_days=14, theta=theta,
                            max_bundle_size=5, mc_samples=1500),
                use_cache=False,
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(t,)) for t in (0.90, 0.97)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert results[0.90]["theta"] == 0.90
    assert results[0.97]["theta"] == 0.97

    # The isolation property: each plan's blocks satisfy that plan's OWN theta.
    # If the two requests had interleaved through core.THETA, one of them would
    # be carrying blocks admitted under the other's reliability floor.
    #
    # Deliberately not asserted: that a stricter theta completes fewer jobs.
    # A column admissible at 0.97 is admissible at 0.90, so the 0.97 column set
    # is a subset -- but the optimiser minimises cost rather than maximising
    # jobs, and this instance has a very wide set of tied optima, so job counts
    # are not reliably monotone in theta.
    for theta, plan in results.items():
        for block in plan["blocks"]:
            assert block["reliability"] >= theta - 0.02, (
                f"block below theta={theta}: {block['reliability']}"
            )


def test_planning_lock_is_held_during_a_plan(service: PlanningService):
    """Verify the lock is actually taken, not merely declared.

    Asserted by observing from another thread that the lock cannot be acquired
    while a plan is in flight. A timing-based test would prove nothing here: a
    plan takes ~12 s regardless, so "it took longer than X" would pass even
    with no lock at all.
    """
    observed_held = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def run_plan():
        try:
            service.plan(BENCHMARK_REQUEST, use_cache=False)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            finished.set()

    planner = threading.Thread(target=run_plan)
    planner.start()
    try:
        deadline = time.perf_counter() + 120
        while not finished.is_set() and time.perf_counter() < deadline:
            # RLock is reentrant per-thread, so a non-blocking acquire from
            # THIS thread fails only while the planner thread holds it.
            if planning_lock().acquire(blocking=False):
                planning_lock().release()
                time.sleep(0.05)
            else:
                observed_held.set()
                break
    finally:
        planner.join(timeout=180)

    assert not errors, errors
    assert observed_held.is_set(), (
        "planning lock was never observed held while a plan was running"
    )


# -- 3. the frozen benchmark ----------------------------------------------

def test_plan_matches_the_frozen_benchmark_row(service: PlanningService):
    """Phase 1 definition of done: reproduce benchmark_results.csv.

    Asserted exactly on the quantities that are invariant across the optimiser's
    degenerate optimal face (objective-determined), and with tolerance on the
    Monte Carlo reliability estimate.

    Block count and cross-department share are deliberately NOT asserted
    exactly: probing the model showed the optimal face for this instance
    contains solutions from 118 to 153 blocks and cross-department shares from
    27.5% to 55.1%, all at the identical optimal objective. Those two figures
    are chosen by CP-SAT tie-breaking, not determined by the model, so pinning
    them would be asserting a solver-version artefact.
    """
    row = _frozen_benchmark_row("NORMAL_TRAFFIC")
    plan = service.plan(BENCHMARK_REQUEST, use_cache=False)
    summary = plan["summary"]
    instance = plan["instance"]

    assert plan["status"] == row["status"]
    assert instance["jobs_after_pairing"] == int(row["jobs_after_pairing"])
    assert instance["bundles"] == int(row["bundles"])
    assert instance["windows"] == int(row["windows"])
    assert instance["columns"] == int(row["columns"])

    # Invariant across tied optima.
    assert summary["traffic_cost"] == pytest.approx(float(row["traffic_cost"]), abs=0.05)
    assert summary["jobs_deferred"] == int(row["deferred"])

    # Monte Carlo estimate: 2 dp is the precision core.evaluate itself reports.
    assert summary["min_reliability"] == pytest.approx(float(row["min_reliability"]), abs=0.01)
    assert summary["mean_reliability"] == pytest.approx(
        float(row["avg_reliability"]), abs=0.01
    )


# -- error semantics (frozen in API_CONTRACT.md) ---------------------------

def test_unknown_scenario_raises_a_404_shaped_error(service: PlanningService):
    with pytest.raises(UnknownScenarioError):
        service.plan(PlanRequest(scenario="NO_SUCH_SCENARIO"))


@pytest.mark.parametrize("kwargs", [
    {"theta": 0.0}, {"theta": 1.0}, {"theta": -0.1}, {"theta": 1.5},
    {"horizon_days": 0}, {"mc_samples": 0}, {"max_bundle_size": 0},
])
def test_invalid_parameters_raise_before_reaching_frozen_code(service, kwargs):
    request = PlanRequest(scenario="NORMAL_TRAFFIC", **kwargs)
    with pytest.raises(ValueError):
        service.plan(request)


def test_infeasible_theta_returns_a_plan_not_an_error(service: PlanningService):
    """"Nothing can be scheduled at theta = 0.999" is a valid answer.

    Returning an error here would be the single most misleading thing the
    backend could do, and would make the theta slider look like a crash.
    """
    plan = service.plan(
        PlanRequest(scenario="NORMAL_TRAFFIC", horizon_days=14, theta=0.999,
                    max_bundle_size=5, mc_samples=1500),
        use_cache=False,
    )
    assert plan["status"] in ("OPTIMAL", "FEASIBLE")
    assert isinstance(plan["blocks"], list)
    assert plan["summary"]["jobs_done"] <= 175
