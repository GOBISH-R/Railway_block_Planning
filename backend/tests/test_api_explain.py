"""HTTP layer for the explanation endpoints: schema, status codes, contract.

Uses FastAPI's TestClient against the real service — the whole point is that
the wire format a React client will consume is what gets asserted.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from blockplan_api.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def plan(client):
    response = client.post("/plan", json={
        "scenario": "NORMAL_TRAFFIC", "horizon_days": 14, "theta": 0.90,
        "max_bundle_size": 5, "mc_samples": 1500,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_plan_endpoint_returns_the_contract_shape(plan):
    for field in ("plan_id", "scenario", "status", "objective", "blocks",
                  "deferred", "summary", "stage_timings_s"):
        assert field in plan
    assert plan["status"] in ("OPTIMAL", "FEASIBLE")


def test_plan_is_retrievable_by_id(client, plan):
    again = client.get(f"/plan/{plan['plan_id']}")
    assert again.status_code == 200
    assert again.json()["plan_id"] == plan["plan_id"]


def test_block_explanation_endpoint(client, plan):
    block = next(b for b in plan["blocks"] if len(b["dept_mix"]) >= 2)
    response = client.get(f"/plan/{plan['plan_id']}/block/{block['block_id']}")
    assert response.status_code == 200, response.text
    body = response.json()

    # Fields this endpoint carried before Phase 2 must
    # all still be present -- Phase 2 extends, it does not reshape.
    for field in ("plan_id", "block_id", "section_id", "day", "start_min",
                  "length", "reliability", "jobs", "departmental_chains",
                  "reliability_by_allowed_length"):
        assert field in body, f"contract field missing: {field}"

    assert body["decision_status"] == "SCHEDULED"
    assert body["jobs"]
    assert body["departmental_chains"]
    assert set(body["reliability_by_allowed_length"]) == {"120", "150", "240"}
    assert body["computation"]["solver_calls"] == 0


def test_explain_endpoint_for_a_deferred_job(client, plan):
    assert plan["deferred"], "no deferred job; test would be vacuous"
    job_id = plan["deferred"][0]["job_id"]
    response = client.post(f"/plan/{plan['plan_id']}/explain/{job_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    for field in ("job_id", "verdict", "candidate_columns"):
        assert field in body, f"contract field missing: {field}"
    assert body["decision_status"] == "DEFERRED"
    assert body["verdict"] in ("INFEASIBLE", "OUTBID", "INFEASIBLE_WHEN_FORCED")
    assert body["applied_theta"] == 0.90
    # The client must be able to decide whether to show a spinner.
    assert isinstance(body["computation"]["resolve_required"], bool)


def test_explain_endpoint_for_a_scheduled_job(client, plan):
    job_id = plan["blocks"][0]["job_ids"][0]
    response = client.post(f"/plan/{plan['plan_id']}/explain/{job_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision_status"] == "SCHEDULED"
    assert body["scheduled_in"]["block_id"] == plan["blocks"][0]["block_id"]


def test_explanation_is_structured_not_prose(client, plan):
    """The frontend needs fields, not a paragraph to parse."""
    block = plan["blocks"][0]
    body = client.get(f"/plan/{plan['plan_id']}/block/{block['block_id']}").json()
    assert isinstance(body["jobs"], list)
    assert isinstance(body["departmental_chains"], list)
    assert isinstance(body["constraints"], dict)
    assert isinstance(body["evidence"], list)
    for item in body["evidence"]:
        assert set(item) >= {"code", "statement", "source", "provenance"}


# -- error semantics -------------------------------------------------------

def test_unknown_plan_and_block_and_job_are_404(client, plan):
    assert client.get("/plan/nosuchplan").status_code == 404
    assert client.get("/plan/nosuchplan/block/B0001").status_code == 404
    assert client.get(f"/plan/{plan['plan_id']}/block/B9999").status_code == 404
    assert client.post(f"/plan/{plan['plan_id']}/explain/J99999").status_code == 404


def test_unknown_scenario_is_404(client):
    response = client.post("/plan", json={"scenario": "NO_SUCH_SCENARIO"})
    assert response.status_code == 404


@pytest.mark.parametrize("body", [
    {"scenario": "NORMAL_TRAFFIC", "theta": 0.0},
    {"scenario": "NORMAL_TRAFFIC", "theta": 1.0},
    {"scenario": "NORMAL_TRAFFIC", "theta": 1.5},
    {"scenario": "NORMAL_TRAFFIC", "horizon_days": 0},
    {"scenario": "NORMAL_TRAFFIC", "mc_samples": 0},
    {"scenario": "NORMAL_TRAFFIC", "unknown_field": 1},
    {},
])
def test_bad_input_is_422_before_reaching_frozen_code(client, body):
    assert client.post("/plan", json=body).status_code == 422


def test_openapi_documents_the_explanation_endpoints(client):
    spec = client.get("/openapi.json").json()
    assert "/plan/{plan_id}/block/{block_id}" in spec["paths"]
    assert "/plan/{plan_id}/explain/{job_id}" in spec["paths"]

