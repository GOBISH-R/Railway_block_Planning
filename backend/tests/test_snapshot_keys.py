"""A plan belongs to a snapshot, and a window set does too.

plan_id is the hash of the six request fields, so the same request against two
different snapshots produces the same id. That is correct -- the id says which
REQUEST -- but it means plan_id alone does not identify a plan. Before this,
plans.plan_id was the sole primary key and save_plan() deletes before inserting,
so persisting a plan against snapshot 2 silently destroyed the snapshot 1 plan.
Not a conflict, not an error: the row and its audit trail were simply gone.

Identity is now (snapshot_id, plan_id). Hashing snapshot_id into plan_id was
the alternative and was rejected: it changes every plan id, including
2db53586d84f which test_reference_plan.py pins and the docs quote, and it
conflates two useful things -- which request, and which plan.

The database tests need a second snapshot to say anything at all, so they
create a throwaway one (its dataset_snapshots row only; the plan tables
reference nothing else) and remove it afterwards.
"""
from __future__ import annotations

import pytest

from blockplan_service import PlanningService, paths
from blockplan_service.persistence import FROZEN_SNAPSHOT_ID, RawPlanValues
from blockplan_service.windows import DEFAULT_KEEP_PER_DAY, WindowCacheKey, key_for

PROBE_SNAPSHOT_ID = 9001


# ---------------------------------------------------------------------------
# The window cache key -- no database needed
# ---------------------------------------------------------------------------

def test_the_window_key_carries_the_snapshot(context):
    """Windows are generated from sections and movements, which are snapshot
    data. Two snapshots sharing a scenario name are not guaranteed to share a
    timetable."""
    row = context.scenario("NORMAL_TRAFFIC")
    assert key_for(row, 14, DEFAULT_KEEP_PER_DAY, 1).snapshot_id == 1
    assert key_for(row, 14).snapshot_id is None


def test_two_snapshots_do_not_share_a_window_set(context):
    row = context.scenario("NORMAL_TRAFFIC")
    assert key_for(row, 14, DEFAULT_KEEP_PER_DAY, 1) != \
        key_for(row, 14, DEFAULT_KEEP_PER_DAY, 2)


def test_the_frozen_csvs_key_on_no_snapshot(csv_context):
    """None, not 1. The CSVs are files and declare no snapshot of their own;
    turning that into 1 is a provenance claim made only where a plan is
    persisted, and it does not belong in a cache key."""
    assert csv_context.snapshot_id is None
    row = csv_context.scenario("NORMAL_TRAFFIC")
    assert key_for(row, 14, DEFAULT_KEEP_PER_DAY, csv_context.snapshot_id) == \
        key_for(row, 14)


def test_everything_else_in_the_key_still_discriminates(context):
    """The snapshot is an addition, not a replacement."""
    row = context.scenario("NORMAL_TRAFFIC")
    base = key_for(row, 14, DEFAULT_KEEP_PER_DAY, 1)
    assert key_for(row, 7, DEFAULT_KEEP_PER_DAY, 1) != base
    assert key_for(row, 14, 4, 1) != base
    assert key_for(context.scenario("PEAK_TRAFFIC"), 14, DEFAULT_KEEP_PER_DAY, 1) \
        != base
    assert key_for(row, 14, DEFAULT_KEEP_PER_DAY, 1) == base, "still hashable/equal"
    assert hash(base) == hash(key_for(row, 14, DEFAULT_KEEP_PER_DAY, 1))


def test_the_key_reads_the_snapshot_off_the_context(context, service):
    """WindowCache.get() takes the context, so the key is derived rather than
    passed in by every caller."""
    before = service.windows.size
    service.windows.get(context, "NORMAL_TRAFFIC", 14)
    assert service.windows.size >= before
    assert all(isinstance(k, WindowCacheKey) and k.snapshot_id == context.snapshot_id
               for k in service.windows.keys())


# ---------------------------------------------------------------------------
# The plan id still identifies the request
# ---------------------------------------------------------------------------

def test_the_plan_id_does_not_depend_on_the_snapshot():
    """Deliberate, and the reason the composite key exists.

    If plan_id hashed the snapshot it would be unique on its own -- and every
    published plan id would change. It does not, so identity is the pair.
    """
    from test_reference_plan import REFERENCE_PLAN_ID, REFERENCE_REQUEST

    assert REFERENCE_REQUEST.cache_key() == REFERENCE_PLAN_ID


def test_a_service_knows_which_snapshot_it_serves(service, context):
    assert service.snapshot_id == context.snapshot_id


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
def second_snapshot():
    """A throwaway snapshot row, so two snapshots exist to be confused.

    Only the dataset_snapshots row: the plan tables reference nothing else, and
    loading 16,189 rows again would test the loader, not this.
    """
    from blockplan_db.connection import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO dataset_snapshots (snapshot_id, label, notice, is_frozen) "
            "VALUES (%s, %s, %s, false) ON CONFLICT (snapshot_id) DO NOTHING",
            (PROBE_SNAPSHOT_ID, "test snapshot (not a dataset)",
             "created by tests/test_snapshot_keys.py"))
        conn.commit()
    yield PROBE_SNAPSHOT_ID
    with connect() as conn:
        conn.execute("DELETE FROM plans WHERE snapshot_id = %s", (PROBE_SNAPSHOT_ID,))
        conn.execute("DELETE FROM dataset_snapshots WHERE snapshot_id = %s",
                     (PROBE_SNAPSHOT_ID,))
        conn.commit()


PLAN_ID = "phase6probe"


def _payload(objective: float, blocks: int) -> dict:
    return {
        "plan_id": PLAN_ID, "scenario": "NORMAL_TRAFFIC", "horizon_days": 14,
        "theta": 0.9, "cache_hit": False, "status": "OPTIMAL",
        "objective": objective,
        "blocks": [
            {"block_id": f"B{n:04d}", "section_id": "JTJ-TPT-UP", "day": n,
             "start_min": 0, "length": 120, "end_min": 120, "reliability": 0.99,
             "traffic_cost": 1.0, "exp_overrun_cost": 2.0,
             "dept_mix": ["ENGG"], "job_ids": [f"J{n:05d}"]}
            for n in range(1, blocks + 1)
        ],
        "deferred": [{"job_id": "J00086", "dept": "SNT"}],
        # A real summary, not a stub. core.evaluate always produces these, and
        # the derived availability block reads them -- a fixture missing
        # jobs_done passes the store tests and then fails the moment a plan is
        # served, which is exactly what happened.
        "summary": {"blocks": blocks, "jobs_done": blocks, "jobs_deferred": 1,
                    "traffic_cost": 12.5},
        "stage_timings_s": {"total": 1.0},
        "instance": {"max_bundle_size": 5, "mc_samples": 1500, "seed": None},
    }


def _raw(objective: float, blocks: int) -> RawPlanValues:
    return RawPlanValues(objective,
                         {f"B{n:04d}": (0.99, 1.0, 2.0) for n in range(1, blocks + 1)})


@pytest.fixture
def two_plans(store, second_snapshot):
    """The same plan id stored against two snapshots, with different contents."""
    store.save_plan(_payload(337.4, 3), snapshot_id=FROZEN_SNAPSHOT_ID,
                    raw=_raw(337.4, 3))
    store.save_plan(_payload(412.9, 2), snapshot_id=second_snapshot,
                    raw=_raw(412.9, 2))
    yield
    from blockplan_db.connection import connect

    with connect() as conn:
        conn.execute("DELETE FROM plans WHERE plan_id = %s", (PLAN_ID,))
        conn.commit()


# -- the bug this phase fixes ------------------------------------------------

@requires_db
def test_a_second_snapshot_no_longer_destroys_the_first_plan(two_plans, store,
                                                             second_snapshot):
    """The measured failure, now a regression test.

    With plan_id as the sole primary key, saving against snapshot 2 deleted the
    snapshot 1 row outright -- silently, because save_plan deletes before
    inserting and re-solving the same request is the normal way to arrive twice.
    """
    assert store.snapshots_holding(PLAN_ID) == (FROZEN_SNAPSHOT_ID, second_snapshot)


@requires_db
def test_each_snapshot_reads_back_its_own_plan(two_plans, store, second_snapshot):
    first = store.load_plan(PLAN_ID, snapshot_id=FROZEN_SNAPSHOT_ID)
    second = store.load_plan(PLAN_ID, snapshot_id=second_snapshot)

    assert first["objective"] == 337.4
    assert second["objective"] == 412.9
    assert len(first["blocks"]) == 3
    assert len(second["blocks"]) == 2
    assert first["plan_id"] == second["plan_id"] == PLAN_ID


@requires_db
def test_blocks_and_deferred_rows_are_separated_too(two_plans, second_snapshot):
    """The child tables carry the snapshot as well, so a plan cannot borrow
    another snapshot's blocks through a shared plan_id."""
    from blockplan_db.connection import connect

    with connect() as conn:
        counts = dict(conn.execute(
            "SELECT snapshot_id, count(*) FROM plan_blocks WHERE plan_id = %s "
            "GROUP BY snapshot_id", (PLAN_ID,)).fetchall())
        deferred = dict(conn.execute(
            "SELECT snapshot_id, count(*) FROM plan_deferred WHERE plan_id = %s "
            "GROUP BY snapshot_id", (PLAN_ID,)).fetchall())
    assert counts == {FROZEN_SNAPSHOT_ID: 3, second_snapshot: 2}
    assert deferred == {FROZEN_SNAPSHOT_ID: 1, second_snapshot: 1}


@requires_db
def test_re_saving_replaces_only_its_own_snapshot(two_plans, store, second_snapshot):
    store.save_plan(_payload(999.9, 1), snapshot_id=second_snapshot,
                    raw=_raw(999.9, 1))

    assert store.load_plan(PLAN_ID, snapshot_id=FROZEN_SNAPSHOT_ID)["objective"] \
        == 337.4
    assert store.load_plan(PLAN_ID, snapshot_id=second_snapshot)["objective"] == 999.9
    assert store.snapshots_holding(PLAN_ID) == (FROZEN_SNAPSHOT_ID, second_snapshot)


@requires_db
def test_approvals_are_separated_by_snapshot(two_plans, store, second_snapshot):
    """A decision is about one plan, and two snapshots' plans are two plans."""
    store.record_approval(PLAN_ID, "B0001", "APPROVED",
                          snapshot_id=FROZEN_SNAPSHOT_ID, decided_by="controller-1")
    store.record_approval(PLAN_ID, "B0001", "REJECTED",
                          snapshot_id=second_snapshot, decided_by="controller-2")

    first = store.approvals_for(PLAN_ID, snapshot_id=FROZEN_SNAPSHOT_ID)
    second = store.approvals_for(PLAN_ID, snapshot_id=second_snapshot)
    assert [a["decision"] for a in first] == ["APPROVED"]
    assert [a["decision"] for a in second] == ["REJECTED"]


# -- what a running service sees --------------------------------------------

@requires_db
def test_a_service_only_restores_its_own_snapshots_plans(two_plans, context, store,
                                                         second_snapshot):
    """A process serving snapshot 1 must not load plans computed from data it
    is not reading."""
    planning = PlanningService(context=context, store=store)
    assert planning.snapshot_id == FROZEN_SNAPSHOT_ID

    planning.restore_plans()
    restored = planning.cached_plan(PLAN_ID)
    assert restored is not None
    assert restored["objective"] == 337.4, "it restored the other snapshot's plan"


@requires_db
def test_a_service_serves_its_own_snapshots_plan_by_id(two_plans, context, store):
    planning = PlanningService(context=context, store=store)
    assert planning.stored_plan(PLAN_ID)["objective"] == 337.4


@requires_db
def test_ids_are_listed_per_snapshot(two_plans, store, second_snapshot):
    assert PLAN_ID in store.plan_ids(snapshot_id=FROZEN_SNAPSHOT_ID)
    assert store.plan_ids(snapshot_id=second_snapshot) == (PLAN_ID,)


@requires_db
def test_a_database_context_keys_windows_on_its_snapshot():
    """The end-to-end version of the window-key change."""
    from blockplan_service import PlanningContext
    from blockplan_service.datasource import DatabaseDataSource

    source = DatabaseDataSource(1)
    try:
        ctx = PlanningContext.load(source)
        assert ctx.snapshot_id == 1
        row = ctx.scenario("NORMAL_TRAFFIC")
        assert key_for(row, 14, DEFAULT_KEEP_PER_DAY, ctx.snapshot_id).snapshot_id == 1
        assert key_for(row, 14, DEFAULT_KEEP_PER_DAY, ctx.snapshot_id) != \
            key_for(row, 14, DEFAULT_KEEP_PER_DAY, None), \
            "a database context must not reuse the CSV context's window set"
    finally:
        source.close()
