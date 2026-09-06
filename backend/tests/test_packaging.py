"""Phase 8 packaging: startup warmup logic and static-file serving.

The real warmup (_warm_all_scenarios against a live PlanningService) is slow
by design -- eight cold plans, a few minutes total -- which is fine once
before a demo and wrong to pay on every pytest run. These tests verify the
LOGIC (every scenario gets warmed, with the frontend's own default
parameters) against a stubbed planner, rather than actually solving eight
times.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from blockplan_api.app import _env_flag, _warm_all_scenarios
from blockplan_service import paths
from blockplan_service.planner import PlanRequest


class _RecordingPlanner:
    """Stands in for PlanningService: same shape, instant, records calls."""

    def __init__(self, scenario_names):
        self.context = type("Ctx", (), {"scenario_names": scenario_names})()
        self.calls: list[PlanRequest] = []

    def plan(self, request: PlanRequest):
        self.calls.append(request)
        return {"plan_id": "stub", "scenario": request.scenario}


def test_env_flag_recognises_common_truthy_spellings():
    for value in ("1", "true", "True", "YES", " yes ", "TRUE"):
        os.environ["BLOCKPLAN_TEST_FLAG"] = value
        assert _env_flag("BLOCKPLAN_TEST_FLAG") is True, value
    del os.environ["BLOCKPLAN_TEST_FLAG"]


def test_env_flag_defaults_false_when_unset_or_other_values():
    os.environ.pop("BLOCKPLAN_TEST_FLAG", None)
    assert _env_flag("BLOCKPLAN_TEST_FLAG") is False
    for value in ("0", "false", "no", "", "warm"):
        os.environ["BLOCKPLAN_TEST_FLAG"] = value
        assert _env_flag("BLOCKPLAN_TEST_FLAG") is False, value
    del os.environ["BLOCKPLAN_TEST_FLAG"]


def test_warm_all_scenarios_plans_every_scenario_exactly_once():
    names = ("NORMAL_TRAFFIC", "PEAK_TRAFFIC", "MAINTENANCE_BACKLOG")
    stub = _RecordingPlanner(names)
    _warm_all_scenarios(stub)
    assert [c.scenario for c in stub.calls] == list(names)


def test_warm_all_scenarios_uses_the_frontend_s_own_defaults():
    """The precomputed plan must be the one the UI actually requests first.

    If these drift apart, warming happens but the frontend's first request
    still misses the cache -- silently defeating the entire point of Phase 8.
    """
    stub = _RecordingPlanner(("NORMAL_TRAFFIC",))
    _warm_all_scenarios(stub)
    request = stub.calls[0]
    assert request.horizon_days == 14
    assert request.theta == 0.90
    assert request.max_bundle_size == 5
    assert request.mc_samples == 1500
    assert request.seed is None


def test_frontend_dist_path_is_under_the_frontend_directory():
    assert paths.FRONTEND_DIST.replace("\\", "/").endswith("frontend/dist")


@pytest.fixture(scope="module")
def client():
    from blockplan_api.app import app

    with TestClient(app) as c:
        yield c


@pytest.mark.skipif(
    not os.path.isdir(paths.FRONTEND_DIST),
    reason="frontend/dist not built -- run `npm run build` in frontend/ first",
)
class TestStaticServingDoesNotShadowTheApi:
    """Only meaningful once a real build exists; skipped otherwise.

    The mount is guarded by that same os.path.isdir check in app.py, so
    skipping here exactly mirrors when the mount itself is (or isn't) active.
    """

    def test_root_serves_the_built_frontend(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_api_routes_still_win_over_the_static_catch_all(self, client):
        """The definitive check: an API path must never fall through to a
        static-file 404 or to index.html (which `html=True` would otherwise
        serve for any unmatched path)."""
        response = client.get("/corridor")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert "stations" in body and "sections" in body

    def test_unknown_path_is_a_real_404_not_index_html(self, client):
        response = client.get("/this-path-does-not-exist-anywhere")
        assert response.status_code == 404


def test_health_reports_cached_plan_count(client):
    body = client.get("/health").json()
    assert "cached_plans" in body
    assert isinstance(body["cached_plans"], int)
