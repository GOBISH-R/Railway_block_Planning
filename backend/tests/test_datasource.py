"""The data-source seam: CSV by default, PostgreSQL when asked.

Split in two. Everything above the "live database" divider runs anywhere and
covers the part most likely to go wrong quietly -- resolution from the
environment, and the guarantee that nothing changes unless someone asks for it.
The tests below the divider need PostgreSQL and skip without it.

The claim being tested is interchangeability: a PlanningContext built from the
database must be indistinguishable from one built from the frozen CSVs. Not
"similar", and not "the same row counts" -- the same sections, the same trains
in the same order, the same jobs, the same pristine RNG state. Anything less
and the plan could still differ, which is what test_db_verify.py then measures
end to end.
"""
from __future__ import annotations

import os

import pytest

from blockplan_service import paths
from blockplan_service.context import PlanningContext
from blockplan_service.datasource import (
    CSV,
    POSTGRES,
    CsvDataSource,
    DatabaseDataSource,
    DataSource,
    DataSourceError,
    resolve,
)

# ---------------------------------------------------------------------------
# Resolution -- no database needed
# ---------------------------------------------------------------------------

def test_the_default_is_the_frozen_csvs():
    """The demo runs with no database installed, and every published number
    came from these files. Silence must mean CSV."""
    source = resolve({})
    assert isinstance(source, CsvDataSource)
    assert source.name == CSV
    assert source.snapshot_id is None


def test_an_unrelated_environment_does_not_switch_the_source():
    assert isinstance(resolve({"PGHOST": "localhost", "PATH": "/usr/bin"}),
                      CsvDataSource)


@pytest.mark.parametrize("value", ["csv", "CSV", " Csv ", ""])
def test_csv_is_accepted_in_any_reasonable_spelling(value):
    assert isinstance(resolve({"BLOCKPLAN_DATA_SOURCE": value}), CsvDataSource)


def test_postgres_is_opt_in_and_defaults_to_snapshot_one():
    source = resolve({"BLOCKPLAN_DATA_SOURCE": POSTGRES})
    assert isinstance(source, DatabaseDataSource)
    assert source.snapshot_id == 1


def test_a_snapshot_can_be_named():
    source = resolve({"BLOCKPLAN_DATA_SOURCE": POSTGRES,
                      "BLOCKPLAN_SNAPSHOT_ID": "7"})
    assert source.snapshot_id == 7


def test_an_unknown_source_is_refused_rather_than_falling_back():
    """Falling back to CSV would look like it worked. Someone who writes
    "postgresql" wants the database and must be told they did not get it."""
    with pytest.raises(DataSourceError) as exc:
        resolve({"BLOCKPLAN_DATA_SOURCE": "postgresql"})
    assert "postgresql" in str(exc.value)
    assert CSV in str(exc.value) and POSTGRES in str(exc.value)


def test_a_nonsense_snapshot_id_is_refused():
    with pytest.raises(DataSourceError):
        resolve({"BLOCKPLAN_DATA_SOURCE": POSTGRES,
                 "BLOCKPLAN_SNAPSHOT_ID": "latest"})


def test_both_sources_satisfy_the_protocol():
    assert isinstance(CsvDataSource(), DataSource)
    assert isinstance(DatabaseDataSource(1), DataSource)


# ---------------------------------------------------------------------------
# The CSV source and the tree it describes
# ---------------------------------------------------------------------------

def test_the_csv_source_is_the_frozen_tree_and_touches_nothing():
    assert CsvDataSource().open() is paths.FROZEN_TREE


def test_the_frozen_tree_is_complete():
    assert paths.FROZEN_TREE.missing() == []


def test_the_tree_agrees_with_the_module_constants():
    """Two spellings of the same locations, and they must not drift: the
    loader and the evidence endpoints still use the constants."""
    tree = paths.FROZEN_TREE
    assert tree.sections_csv == paths.SECTIONS_CSV
    assert tree.stations_csv == paths.STATIONS_CSV
    assert tree.movements_csv == paths.MOVEMENTS_CSV
    assert tree.pairing_rules_csv == paths.PAIRING_RULES_CSV
    assert tree.scenarios_csv == paths.SCENARIOS_CSV
    assert tree.scenario_jobs_dir == paths.SCENARIO_JOBS_DIR
    assert tree.scenario_jobs_csv("NORMAL_TRAFFIC") == \
        paths.scenario_jobs_csv("NORMAL_TRAFFIC")


def test_an_empty_directory_is_reported_as_incomplete(tmp_path):
    missing = paths.DatasetTree(str(tmp_path)).missing()
    assert len(missing) == 5
    with pytest.raises(DataSourceError):
        _EmptySource(str(tmp_path)).open()


class _EmptySource:
    """A CsvDataSource pointed somewhere empty, to exercise the guard."""

    name = CSV
    snapshot_id = None

    def __init__(self, root: str) -> None:
        self._tree = paths.DatasetTree(root)

    def open(self) -> paths.DatasetTree:
        missing = self._tree.missing()
        if missing:
            raise DataSourceError(f"incomplete: {missing}")
        return self._tree

    def describe(self) -> str:
        return f"tree at {self._tree.root}"


# ---------------------------------------------------------------------------
# The context carries its source
# ---------------------------------------------------------------------------

def test_the_context_knows_which_tree_it_was_built_from(csv_context: PlanningContext):
    """Everything downstream reads context.tree, so if this were wrong the
    planner would reload frozen pairing rules over a database context.

    Pinned to the CSV source rather than the ambient one: this is a claim about
    the CSV path, and the suite is also run with BLOCKPLAN_DATA_SOURCE=postgres.
    """
    assert csv_context.tree == paths.FROZEN_TREE
    assert paths.DATASET_DIR in csv_context.source_description


def test_loading_from_a_tree_directly_is_supported(context: PlanningContext):
    """Tools that already know which directory they want should not have to
    construct a DataSource to say so."""
    other = PlanningContext.load(paths.FROZEN_TREE)
    assert other.tree == paths.FROZEN_TREE
    assert other.section_ids == context.section_ids


# ---------------------------------------------------------------------------
# Live database
# ---------------------------------------------------------------------------

from blockplan_db.connection import is_configured  # noqa: E402

requires_db = pytest.mark.skipif(
    not is_configured(), reason="no database configured (BLOCKPLAN_DATABASE_URL / PG*)"
)


@pytest.fixture(scope="module")
def db_source():
    source = DatabaseDataSource(1)
    yield source
    source.close()


@pytest.fixture(scope="module")
def db_context(db_source):
    return PlanningContext.load(db_source)


@requires_db
def test_the_database_source_materialises_a_complete_tree(db_source):
    tree = db_source.open()
    assert tree.missing() == []
    assert tree.root != paths.DATASET_DIR, "it must not be reading the frozen files"
    for scenario in ("NORMAL_TRAFFIC", "PEAK_TRAFFIC"):
        assert os.path.isfile(tree.scenario_jobs_csv(scenario)), scenario


@requires_db
def test_opening_twice_reuses_the_same_tree(db_source):
    """Startup cost, paid once. A second open() that re-materialised would
    quietly double it and hand out a different directory."""
    assert db_source.open() is db_source.open()


@requires_db
def test_the_database_source_names_the_snapshot_it_read(db_source):
    db_source.open()
    described = db_source.describe()
    assert "snapshot 1" in described
    assert "frozen" in described


@requires_db
def test_a_missing_snapshot_is_named_rather_than_producing_an_empty_tree():
    from blockplan_db.repository import SnapshotNotFoundError

    with pytest.raises(SnapshotNotFoundError) as exc:
        DatabaseDataSource(4242).open()
    assert "4242" in str(exc.value)


# -- the claim: the two contexts are interchangeable ------------------------

@requires_db
def test_the_materialised_tree_outlives_the_source_reference(tmp_path):
    """The context must keep the materialised tree alive.

    DatabaseDataSource owns a TemporaryDirectory whose finaliser deletes the
    tree. resolve() builds the source inside PlanningContext.load() and no
    caller ever sees it, so if the context did not hold it, it would be
    collected and the directory deleted -- while the context still pointed at
    it. Startup survives that, because sections, trains and jobs are already in
    memory; the failure lands later, on the first per-request file read, which
    is /demand and /corridor.

    This test reproduces it: build the context, drop every other reference to
    the source, collect, then read a file the context reads lazily. Found by
    driving the real API, not by this suite -- the fixtures were holding the
    source and hiding it.
    """
    import gc

    from blockplan_service.reference_data import demand_payload

    ctx = PlanningContext.load(DatabaseDataSource(1))
    root = ctx.tree.root
    gc.collect()

    assert os.path.isdir(root), "the materialised tree was collected away"
    payload = demand_payload(ctx, "NORMAL_TRAFFIC")
    assert len(payload["jobs"]) == 175


@requires_db
def test_the_same_sections_in_the_same_order(db_context, context):
    assert db_context.sections == context.sections


@requires_db
def test_the_same_trains_in_the_same_order(db_context, context):
    """Order, not just membership. load_trains() builds each Train id from the
    row's file position, so a reordering shows up here as different ids -- and
    would go on to change the plan."""
    assert db_context.trains == context.trains


@requires_db
def test_the_same_scenarios_and_the_same_declared_parameters(db_context, context):
    assert db_context.scenario_names == context.scenario_names
    for name in context.scenario_names:
        assert dict(db_context.scenario(name)) == dict(context.scenario(name)), name


@requires_db
def test_the_same_jobs_for_every_scenario(db_context, context):
    for name in context.scenario_names:
        assert db_context.jobs_for(name) == context.jobs_for(name), name


@requires_db
def test_the_same_pairing_rules_with_their_citations(db_context, context):
    assert db_context.pairing_rule_count == context.pairing_rule_count
    assert db_context.pairing_rules == context.pairing_rules


@requires_db
def test_the_same_presentation_geography(db_context, context):
    assert db_context.stations == context.stations
    assert db_context.section_meta == context.section_meta


@requires_db
def test_the_same_pristine_rng_state(db_context, context):
    """The determinism anchor. Equal data with a different starting RNG state
    would still plan differently.

    This is the assertion that caught it: it passed alone and failed in the
    full suite, because solves in the earlier test files had drawn from
    core.RNG between the two loads and load() was snapshotting whatever it
    found. See _PRISTINE_RNG_STATE in context.py.
    """
    assert dict(db_context.pristine_rng_state) == dict(context.pristine_rng_state)
