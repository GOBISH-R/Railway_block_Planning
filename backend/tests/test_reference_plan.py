"""The reference plan: the result every change must keep reproducing.

`test_frozen_artifacts.py` guards the input FILES -- their bytes and hashes.
This guards the OUTPUT: the concrete plan those files produce when the pipeline
runs. The two are independent. A change that leaves every input byte intact can
still alter the plan (a solver parameter, a load-order change, a different
float path), and the frozen CSVs would not notice.

It exists as the gate for work that touches how data reaches the planner --
the PostgreSQL data layer first. Moving 16,000 rows into a database is correct
only if the planner still produces this exact plan from them. Row-by-row
fidelity is necessary but not sufficient: values can survive a round trip and
still arrive in a different order, or as a different float, and change the
answer. This test is what makes that visible.

Deliberately expensive: it forces a real solve with `use_cache=False`, which is
the point. A cached plan proves nothing about the pipeline.
"""
from __future__ import annotations

import csv
import hashlib

import pytest

from blockplan_service import PlanRequest, PlanningService, paths

REFERENCE_SCENARIO = "NORMAL_TRAFFIC"

# The benchmark request: the parameters that produced every number this project
# quotes. Each field is stated rather than defaulted, because cache_key() hashes
# all six and a silent default change would move the plan id.
REFERENCE_REQUEST = PlanRequest(
    scenario=REFERENCE_SCENARIO,
    horizon_days=14,
    theta=0.90,
    max_bundle_size=5,
    mc_samples=1500,
    seed=None,
)

REFERENCE_PLAN_ID = "2db53586d84f"

# sha256 over every block's identity and raw geometry, in plan order. This is
# the assertion that catches a plan which is equally optimal but concretely
# different -- the instance is degenerate, so the objective alone cannot.
#
# Regenerate ONLY with a recorded, deliberate decision to re-baseline. If this
# fails, the plan changed; that is a finding, not a maintenance chore.
REFERENCE_BLOCK_FINGERPRINT = (
    "6f509bae39c8a032ce99201370b8c8522734a0b247f56bc4d61dcc894600b429"
)

REFERENCE_DEFERRED = ("J00086",)


@pytest.fixture(scope="module")
def reference(service: PlanningService):
    """The reference plan and its retained artefacts, solved once."""
    plan = service.plan(REFERENCE_REQUEST, use_cache=False)
    return plan, service.internals(plan["plan_id"])


def block_fingerprint_parts(internals) -> list[str]:
    """One canonical line per block, from the raw artefacts.

    Reads `repr()` of the floats rather than the DTO's rounded values: the
    response rounds reliability to 3 places, which would hide a small drift in
    the Monte Carlo or the traffic model. This has to see it.
    """
    parts = []
    for block_id, column in internals.blocks_by_id.items():
        window = column.window
        parts.append(
            "|".join(
                [
                    block_id,
                    window.section_id,
                    str(window.day),
                    str(window.start_min),
                    str(window.length),
                    str(window.end_min),
                    ",".join(column.job_ids),
                    repr(column.reliability),
                    repr(column.exp_overrun_cost),
                    repr(window.traffic_cost),
                ]
            )
        )
    return parts


def frozen_benchmark_row(scenario: str) -> dict:
    with open(paths.BENCHMARK_RESULTS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["scenario"] == scenario:
                return row
    raise AssertionError(f"{scenario} missing from benchmark_results.csv")


# -- identity ---------------------------------------------------------------

def test_reference_request_still_hashes_to_the_published_plan_id(reference):
    """The plan id is quoted in the demo pack and in explanation URLs.

    It is derived from the six request fields, so this fails if any default
    moves or cache_key() changes shape -- either of which would silently
    invalidate every stored plan reference.
    """
    plan, _ = reference
    assert plan["plan_id"] == REFERENCE_PLAN_ID
    assert REFERENCE_REQUEST.cache_key() == REFERENCE_PLAN_ID


def test_reference_plan_is_solved_to_proven_optimality(reference):
    plan, _ = reference
    assert plan["status"] == "OPTIMAL"
    assert plan["cache_hit"] is False, "a cached plan would not exercise the pipeline"


# -- agreement with the frozen benchmark ------------------------------------

def test_plan_still_matches_the_frozen_benchmark_row(reference):
    """Ties the computed plan to benchmark_results.csv.

    Expected values are read from the frozen CSV rather than restated here, so
    the two can never drift apart in this file. The CSV holds full-precision
    values while the response rounds to the documented precision, hence the rounding on
    the CSV side rather than a loosened comparison.
    """
    plan, _ = reference
    row = frozen_benchmark_row(REFERENCE_SCENARIO)
    summary = plan["summary"]

    assert plan["status"] == row["status"]
    assert summary["blocks"] == int(row["blocks"])
    assert summary["jobs_deferred"] == int(row["deferred"])
    assert plan["instance"]["jobs_after_pairing"] == int(row["jobs_after_pairing"])
    assert summary["traffic_cost"] == round(float(row["traffic_cost"]), 1)
    assert summary["mean_reliability"] == round(float(row["avg_reliability"]), 2)
    assert summary["min_reliability"] == round(float(row["min_reliability"]), 2)


def test_headline_figures_are_unchanged(reference):
    """The numbers on the summary strip, stated explicitly.

    Redundant with the CSV comparison by design: if someone re-baselines the
    CSV, this still fails and forces the change to be acknowledged twice.
    """
    plan, _ = reference
    assert plan["objective"] == 337.4
    assert plan["summary"]["blocks"] == 140
    assert plan["summary"]["jobs_done"] == 174
    assert plan["summary"]["jobs_deferred"] == 1
    assert plan["summary"]["traffic_cost"] == 299.2
    assert plan["summary"]["exp_overrun_cost"] == 38.6
    assert plan["summary"]["min_reliability"] == 0.9


def test_pipeline_stage_sizes_are_unchanged(reference):
    """The funnel each stage produces -- rules, search, pricing, risk filter.

    A data layer that loads the same rows in a different order, or drops a
    duplicate, shows up here before it shows up as a different plan.
    """
    plan, _ = reference
    assert plan["instance"] == {
        "base_jobs": 175,
        "jobs_after_pairing": 238,   # rule inference adds 63 companions
        "bundles": 449,              # compatibility-graph cliques
        "windows": 11648,            # priced against the real timetable
        "columns": 16746,            # survived the theta chance constraint
        "mc_samples": 1500,
        "max_bundle_size": 5,
        "seed": None,
    }


# -- the concrete plan ------------------------------------------------------

def test_the_same_140_blocks_are_chosen(reference):
    """Checked before the fingerprint so a count or id change reads clearly."""
    _, internals = reference
    block_ids = list(internals.blocks_by_id.keys())
    assert len(block_ids) == 140
    assert block_ids == [f"B{n:04d}" for n in range(1, 141)]


def test_the_same_job_is_deferred(reference):
    _, internals = reference
    assert tuple(internals.deferred_job_ids) == REFERENCE_DEFERRED


def test_block_contents_are_byte_identical(reference):
    """The strongest assertion here, and the reason this file exists.

    The instance is degenerate -- thousands of plans share the optimal
    objective, and block count alone spans 118 to 153 on the optimal face. So
    matching aggregates proves nothing about WHICH plan came back. This pins
    every block's section, day, window, job set and raw reliability.
    """
    _, internals = reference
    parts = block_fingerprint_parts(internals)
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    assert digest == REFERENCE_BLOCK_FINGERPRINT, (
        "the concrete plan changed while its headline numbers may not have.\n"
        f"  blocks: {len(parts)}\n"
        f"  first:  {parts[0]}\n"
        f"  last:   {parts[-1]}\n"
        "Compare against the previous plan before re-baselining this constant."
    )
