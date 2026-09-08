"""API contract compatibility.

The service produces the POST /plan response body and the HTTP layer serves
it. These tests pin that shape, and the set of endpoints, so neither drifts
silently under the frontend that is written against them.

The contract was originally written down in API_CONTRACT.md and these tests
read it. That document has been removed, so the endpoint guard now asserts
against the route table FastAPI actually registers. That is the stronger
check: a markdown file can drift out of agreement with the code and still
pass its own grep, a route table cannot.
"""
from __future__ import annotations

import json
import os

import pytest

from blockplan_service import PlanRequest, paths

FIXTURE_JSON = os.path.join(paths.REPO_ROOT, "plan.json")

# Exactly the fields the POST /plan response carries.
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
    """`instance`, `cache_hit` and `availability` are additions; everything else
    must be in the contract.

    Additive fields are a compatible change, but they must be deliberate --
    this test fails if a fourth one appears without the contract being updated.
    It did exactly that when `availability` was added, which is the point.
    """
    assert set(plan) - PLAN_FIELDS == {"instance", "cache_hit", "availability"}


def test_availability_travels_with_its_work_figures(plan):
    """Asset availability is maximised by doing no maintenance, so the response
    must never carry the percentage on its own. See availability.py."""
    report = plan["availability"]
    for key in ("availability", "jobs_done", "jobs_deferred",
                "traffic_delay_minutes", "headline"):
        assert key in report, key
    assert report["jobs_done"] == plan["summary"]["jobs_done"]
    assert report["jobs_deferred"] == plan["summary"]["jobs_deferred"]
    assert 0.0 <= report["availability"] <= 1.0
    assert str(report["jobs_done"]) in report["headline"]


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


EXPECTED_ENDPOINTS = {
    ("GET", "/corridor"),
    ("GET", "/scenarios"),
    ("GET", "/demand"),
    ("GET", "/traffic"),
    ("GET", "/comparison"),
    ("GET", "/health"),
    ("POST", "/plan"),
    ("GET", "/plan/{plan_id}"),
    ("GET", "/plan/{plan_id}/block/{block_id}"),
    ("POST", "/plan/{plan_id}/explain/{job_id}"),
}


def test_the_served_endpoints_are_exactly_the_expected_set():
    """Guard against an endpoint being added, renamed or dropped unnoticed.

    Equality, not containment, and deliberately so. Containment would let a new
    endpoint appear with no test and no note; a frontend written against this
    surface should not discover routes by accident.
    """
    from blockplan_api.app import app

    served = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", "")
        if not methods or path in ("/openapi.json", "/docs", "/redoc",
                                   "/docs/oauth2-redirect"):
            continue
        for method in methods - {"HEAD", "OPTIONS"}:
            served.add((method, path))

    # The static mount that serves the built frontend is not part of the API
    # surface and carries no methods of its own.
    served = {(m, p) for m, p in served if p != "/"}

    assert served == EXPECTED_ENDPOINTS, (
        f"unexpected: {sorted(served - EXPECTED_ENDPOINTS)}; "
        f"missing: {sorted(EXPECTED_ENDPOINTS - served)}"
    )
