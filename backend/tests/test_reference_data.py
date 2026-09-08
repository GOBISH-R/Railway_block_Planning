"""The five data-serving endpoints added for Phase 3's frontend.

Pure reads: no plan is created, no solver runs. Counts are asserted against
the frozen dataset's own documented numbers so a regression here is caught
immediately rather than discovered by a blank corridor view.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from blockplan_api.app import app

    with TestClient(app) as c:
        yield c


def test_corridor_matches_the_frozen_network(client):
    body = client.get("/corridor").json()
    assert len(body["stations"]) == 27
    assert len(body["sections"]) == 52
    codes = [s["station_code"] for s in body["stations"]]
    assert codes[0] == "JTJ" and codes[-1] == "ED"
    assert all(s["seq"] == i for i, s in enumerate(body["stations"]))
    for section in body["sections"]:
        assert section["line"] in ("UP", "DN")
        assert section["length_km"] > 0


def test_scenarios_lists_all_eight_with_job_counts(client):
    body = client.get("/scenarios").json()["scenarios"]
    names = {s["name"] for s in body}
    assert names == {
        "NORMAL_TRAFFIC", "PEAK_TRAFFIC", "HEAVY_FREIGHT", "MAINTENANCE_BACKLOG",
        "URGENT_MAINTENANCE", "HIGH_DURATION_UNCERTAINTY", "DISRUPTED_OPERATION",
        "MULTIPLE_DEPARTMENT_REQUESTS",
    }
    by_name = {s["name"]: s for s in body}
    assert by_name["NORMAL_TRAFFIC"]["realised_job_count"] == 175
    assert by_name["MAINTENANCE_BACKLOG"]["realised_job_count"] == 340
    assert by_name["PEAK_TRAFFIC"]["extra_passenger_scale"] == 1.35
    assert by_name["NORMAL_TRAFFIC"]["extra_passenger_scale"] is None


def test_demand_returns_the_scenarios_own_job_set(client):
    body = client.get("/demand", params={"scenario": "NORMAL_TRAFFIC"}).json()
    assert body["scenario"] == "NORMAL_TRAFFIC"
    assert len(body["jobs"]) == 175
    depts = {j["dept"] for j in body["jobs"]}
    assert depts == {"ENGG", "SNT", "TRD"}
    # UI-only labels core.Job does not carry must still be present here.
    for job in body["jobs"]:
        assert job["priority"] in ("URGENT", "NORMAL", "HIGH", "MEDIUM", "LOW") or job["priority"]
        assert job["uncertainty_level"]


def test_demand_unknown_scenario_is_404(client):
    assert client.get("/demand", params={"scenario": "NOPE"}).status_code == 404


def test_traffic_normal_scenario_matches_the_real_timetable(client):
    body = client.get("/traffic", params={"scenario": "NORMAL_TRAFFIC"}).json()
    assert len(body["movements"]) == 2978
    assert sum(1 for m in body["movements"] if m["is_synthetic"]) == 410


def test_traffic_peak_scenario_adds_synthetic_passenger_movements(client):
    normal = client.get("/traffic", params={"scenario": "NORMAL_TRAFFIC"}).json()
    peak = client.get("/traffic", params={"scenario": "PEAK_TRAFFIC"}).json()
    assert len(peak["movements"]) > len(normal["movements"]), (
        "PEAK_TRAFFIC should add synthetic passenger paths on top of the real timetable"
    )
    added = [m for m in peak["movements"] if m["train_number"].startswith("PEAK_SYN_")]
    assert added and all(m["is_synthetic"] for m in added)


def test_traffic_filters_by_section(client):
    body = client.get("/traffic", params={"scenario": "NORMAL_TRAFFIC",
                                          "section_id": "JTJ-TPT-UP"}).json()
    assert body["movements"]
    assert all(m["section_id"] == "JTJ-TPT-UP" for m in body["movements"])


def test_derived_availability_agrees_with_the_frozen_rows_it_came_from(client):
    """It is computed from method_comparison and execution_scoring_blocks, so
    it cannot be allowed to disagree with them -- that is the whole reason it
    is derived rather than stored as a fourth CSV."""
    body = client.get("/comparison").json()
    frozen = {row["method"]: row for row in body["method_comparison"]}

    assert set(body["asset_availability"]) == set(frozen)
    for method, report in body["asset_availability"].items():
        assert report["jobs_done"] == int(frozen[method]["jobs_done"])
        assert report["traffic_delay_minutes"] == float(frozen[method]["traffic_cost"])
        # and the metric never travels without its work figure
        assert str(report["jobs_done"]) in report["headline"]


def test_the_improvement_is_reported_with_the_work_it_bought(client):
    body = client.get("/comparison").json()
    improvement = body["asset_availability_improvement"]
    assert improvement["jobs_gained"] == 13
    assert improvement["section_hours_released"] == 58.5
    assert "jobs" in improvement["headline"]


def test_comparison_serves_the_frozen_artefacts_verbatim(client):
    """Numbers here must match the source CSV exactly -- this is a reader."""
    import csv as _csv

    from blockplan_service import paths

    body = client.get("/comparison").json()
    assert set(body) == {"method_comparison", "execution_scoring_summary",
                         "benchmark_results",
                         # DERIVED from the two above, not a fourth artefact,
                         # and named separately so a reader can tell which
                         # numbers are frozen and which are computed here.
                         "asset_availability", "asset_availability_improvement"}

    with open(paths.BENCHMARK_RESULTS_CSV, encoding="utf-8") as f:
        frozen_rows = list(_csv.DictReader(f))

    served = {row["scenario"]: row for row in body["benchmark_results"]}
    for frozen in frozen_rows:
        row = served[frozen["scenario"]]
        assert row["blocks"] == int(frozen["blocks"])
        assert row["traffic_cost"] == pytest.approx(float(frozen["traffic_cost"]))


def test_health_endpoint_reports_state(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["scenarios"] == 8
    assert body["sections"] == 52
