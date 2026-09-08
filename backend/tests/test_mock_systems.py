"""The mock TMS/SMMS/TDMS endpoints, and pulling a feed over HTTP.

Two things are worth testing here and one thing is not.

Worth testing: that a feed fetched over HTTP is treated identically to one read
from disk -- same contract, same validation, same mapping -- and that the whole
chain still produces the reference plan. If the wire format leaked into
anything downstream, that is where it would show.

Also worth testing: that the server says plainly it is not a real system. The
single most likely way this feature misleads someone is by being described as a
TMS simulator, and the endpoint that would be quoted is /health.

NOT worth testing: the HTTP server itself. It is thirty lines of stdlib and a
demonstration aid; it is not in the planning path and never will be.

Every test binds to loopback on an ephemeral port and shuts the server down.
"""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request

import pytest

from blockplan_ingest import feeds, mock_systems
from blockplan_ingest.contract import SOURCE_SYSTEMS
from blockplan_ingest.datasource import FeedDataSource, FeedDataSourceError


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """The frozen dataset, published as work orders, over HTTP."""
    feed_dir = mock_systems.build_default_feed(
        str(tmp_path_factory.mktemp("served") / "feed"))
    server = mock_systems.serve(feed_dir, port=_free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url: str):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


# -- what the server says about itself ---------------------------------------

def test_health_states_that_it_is_not_a_real_system(served):
    """The likeliest way this misleads someone is by being called a TMS
    simulator. The disclaimer lives where it would be quoted from."""
    body = _get(f"{served}/health")
    assert body["status"] == "ok"
    assert set(body["systems"]) == set(SOURCE_SYSTEMS)
    assert "not a real" in body["notice"].lower()
    assert "emulation" in body["notice"].lower()


def test_the_root_lists_the_endpoints(served):
    body = _get(f"{served}/")
    assert "/tms/work-orders" in body["endpoints"]
    assert "/health" in body["endpoints"]


def test_an_unknown_endpoint_is_a_404_that_says_what_exists(served):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{served}/erp/work-orders")
    assert exc.value.code == 404
    assert "/tms/work-orders" in json.load(exc.value)["endpoints"]


# -- the work orders ---------------------------------------------------------

@pytest.mark.parametrize("system,expected", [("tms", 79), ("smms", 49),
                                             ("tdms", 47)])
def test_each_system_serves_its_own_departments_work(served, system, expected):
    body = _get(f"{served}/{system}/work-orders")
    assert body["source_system"] == system.upper()
    assert len(body["work_orders"]) == expected


def test_the_three_endpoints_carry_the_whole_backlog(served):
    total = sum(len(_get(f"{served}/{s.lower()}/work-orders")["work_orders"])
                for s in SOURCE_SYSTEMS)
    assert total == 175


# -- fetching is reading, by another route -----------------------------------

def test_fetching_produces_the_same_records_as_reading(served, tmp_path_factory):
    """The wire format must not survive past the fetch. If it did, everything
    downstream would have two shapes to handle instead of one."""
    directory = mock_systems.build_default_feed(
        str(tmp_path_factory.mktemp("compare") / "feed"))

    from_disk = {f.source_system: f.records for f in feeds.read_all(directory)}
    from_http = {f.source_system: f.records for f in feeds.fetch_all(served)}

    assert set(from_disk) == set(from_http)
    for system in from_disk:
        assert len(from_disk[system]) == len(from_http[system])
        by_id = {r["work_order_id"]: r for r in from_http[system]}
        for record in from_disk[system]:
            assert by_id[record["work_order_id"]] == record


def test_a_refused_connection_is_reported_not_swallowed():
    with pytest.raises(feeds.FeedError) as exc:
        feeds.fetch_feed(f"http://127.0.0.1:{_free_port()}", "TMS", timeout=2.0)
    assert "tms/work-orders" in str(exc.value)


def test_a_missing_system_can_be_tolerated_over_http(served):
    fetched = feeds.fetch_all(served, systems=("TMS", "TDMS"))
    assert {f.source_system for f in fetched} == {"TMS", "TDMS"}


# -- the source --------------------------------------------------------------

def test_a_url_and_a_directory_together_are_refused(tmp_path):
    """Which backlog was planned is the one thing a plan must not be vague
    about."""
    with pytest.raises(FeedDataSourceError) as exc:
        FeedDataSource(str(tmp_path), base_url="http://localhost:1")
    assert "exactly one" in str(exc.value)


def test_neither_a_url_nor_a_directory_is_refused():
    from blockplan_ingest.datasource import from_env

    with pytest.raises(FeedDataSourceError) as exc:
        from_env({})
    assert "BLOCKPLAN_FEED_URL" in str(exc.value)


def test_the_source_names_the_url_it_pulled_from(served):
    source = FeedDataSource(base_url=served)
    try:
        source.open()
        assert served in source.describe()
        assert "175 work orders" in source.describe()
    finally:
        source.close()


def test_a_url_feed_is_reachable_through_the_data_source_seam(served):
    from blockplan_service.datasource import resolve

    source = resolve({"BLOCKPLAN_DATA_SOURCE": "feed",
                      "BLOCKPLAN_FEED_URL": served})
    try:
        assert source.name == "feed"
        assert source.open().missing() == []
    finally:
        source.close()


# -- the gate, over the wire -------------------------------------------------

@pytest.mark.slow
def test_planning_from_http_endpoints_reproduces_the_reference_plan(served,
                                                                    tmp_path):
    """The demonstration claim, asserted rather than shown once by hand.

    Work orders pulled over HTTP from three endpoints named after TMS, SMMS and
    TDMS, ingested through the real adapter, produce plan 2db53586d84f with the
    identical 140-block fingerprint.
    """
    from blockplan_ingest import verify
    from blockplan_ingest.datasource import materialise

    tree, validation = materialise(None, str(tmp_path / "tree"), base_url=served)
    assert len(validation.accepted) == 175
    assert not validation.rejected

    plan = verify.plan_from(tree.root)
    assert plan.matches_reference, plan
    assert plan.objective == 337.4
    assert plan.blocks == 140
