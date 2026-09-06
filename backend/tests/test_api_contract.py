"""API contract compatibility.

Phase 2 builds the HTTP layer, but the service already produces the POST /plan
response body. These tests pin that shape to API_CONTRACT.md so the contract
cannot drift silently before the frontend is written against it.
"""
from __future__ import annotations

import json
import os

import pytest

from blockplan_service import PlanRequest, paths

CONTRACT_MD = os.path.join(paths.REPO_ROOT, "API_CONTRACT.md")
FIXTURE_JSON = os.path.join(paths.REPO_ROOT, "plan.json")

# Exactly the fields API_CONTRACT.md documents for the POST /plan response.
PLAN_FIELDS = {
    "plan_id", "scenario", "horizon_days", "theta", "status", "objective",
    "blocks", "deferred", "summary", "stage_timings_s",
}
BLOCK_FIELDS = {
    "block_id", "section_id", "day", "start_min", "length", "end_min",
    "reliability", "traffic_cost", "exp_overrun_cost", "dept_mix", "job_ids",
}
DEFERRED_FIELDS = {"job_id", "dept"}
SUMMARY_FIELDS = {
    "blocks", "jobs_done", "jobs_deferred", "traffic_cost", "traffic_per_job",
    "exp_overrun_cost", "cross_dept_blocks", "cross_dept_share",
    "min_reliability", "mean_reliability", "block_utilisation",
}


@pytest.fixture(scope="module")
def plan(service):
    return service.plan(
        PlanRequest(scenario="NORMAL_TRAFFIC", horizon_days=14, theta=0.90,
                    max_bundle_size=5, mc_samples=1500)
    )


def test_response_carries_every_contract_field(plan):
    assert PLAN_FIELDS <= set(plan), f"missing: {PLAN_FIELDS - set(plan)}"


def test_no_undocumented_top_level_fields(plan):
    """`instance` is an addition; everything else must be in the contract.

    Additive fields are a compatible change, but they must be deliberate --
    this test fails if a third one appears without the contract being updated.
    """
    assert set(plan) - PLAN_FIELDS == {"instance"}


def test_block_shape(plan):
    assert plan["blocks"], "expected a non-empty plan for the benchmark request"
    for block in plan["blocks"]:
        assert set(block) == BLOCK_FIELDS, f"block field drift: {set(block) ^ BLOCK_FIELDS}"
        assert block["end_min"] == block["start_min"] + block["length"]
        assert block["length"] in (120, 150, 240), block["length"]
        assert 0.0 <= block["reliability"] <= 1.0
        assert block["dept_mix"] == sorted(block["dept_mix"])
        assert set(block["dept_mix"]) <= {"ENGG", "SNT", "TRD"}
        assert block["job_ids"]


def test_deferred_shape(plan):
    for entry in plan["deferred"]:
        assert set(entry) == DEFERRED_FIELDS
        assert entry["dept"] in {"ENGG", "SNT", "TRD"}


def test_summary_is_core_evaluate_passed_through(plan):
    assert set(plan["summary"]) == SUMMARY_FIELDS


def test_response_is_json_serialisable(plan):
    """It goes over HTTP in Phase 2; numpy scalars would break that."""
    encoded = json.dumps(plan)
    assert json.loads(encoded)["plan_id"] == plan["plan_id"]


def test_matches_the_phase_0_fixture_shape(plan):
    """The frontend is being built against plan.json -- keep them the same shape."""
    with open(FIXTURE_JSON, encoding="utf-8") as f:
        fixture = json.load(f)
    fixture_fields = {k for k in fixture if not k.startswith("_")}

    assert fixture_fields <= set(plan), (
        f"fixture has fields the service does not produce: {fixture_fields - set(plan)}"
    )
    assert set(fixture["blocks"][0]) == BLOCK_FIELDS
    assert set(fixture["deferred"][0]) == DEFERRED_FIELDS
    assert set(fixture["summary"]) == SUMMARY_FIELDS


def test_contract_document_still_describes_these_endpoints():
    """Guard against the contract being edited out from under the service."""
    with open(CONTRACT_MD, encoding="utf-8") as f:
        text = f.read()
    for endpoint in ("GET /corridor", "GET /scenarios", "GET /demand", "GET /traffic",
                     "POST /plan", "GET /plan/{plan_id}",
                     "GET /plan/{plan_id}/block/{block_id}",
                     "POST /plan/{plan_id}/explain/{job_id}", "GET /comparison"):
        assert endpoint in text, f"{endpoint} missing from API_CONTRACT.md"
