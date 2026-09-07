"""The Phase 3 gate: PostgreSQL must be a faithful substitute for the CSVs.

Unlike test_db_loader.py, these need a live database and are skipped without
one, so the suite still passes on a machine that has never installed
PostgreSQL. Configure with BLOCKPLAN_DATABASE_URL or the PG* variables.

Two levels, and the second is the one that matters. Row fidelity is necessary
and not sufficient: values can survive the round trip intact and still arrive
in a different ORDER, which changes the plan. That is not hypothetical here --
`test_row_order_is_load_bearing` measures it -- so the gate ends by rebuilding
the reference plan out of the database and comparing it to the constants
test_reference_plan.py pins.

The plan tests are slow (a real solve each, no cache) and run in subprocesses.
Both are deliberate; see blockplan_db/verify.py.
"""
from __future__ import annotations

import csv
import os

import pytest

from blockplan_db import verify
from blockplan_db.connection import is_configured
from blockplan_service import paths

from test_reference_plan import REFERENCE_BLOCK_FINGERPRINT, REFERENCE_PLAN_ID

pytestmark = pytest.mark.skipif(
    not is_configured(), reason="no database configured (BLOCKPLAN_DATABASE_URL / PG*)"
)

EXPECTED_TABLES = 21
EXPECTED_ROWS = 16189

# What the frozen CSVs are known to produce, from test_reference_plan.py. Stated
# rather than recomputed so the database is compared against the published
# figures, not against whatever this machine happens to produce today.
REFERENCE = verify.Plan(REFERENCE_PLAN_ID, REFERENCE_BLOCK_FINGERPRINT, 140, 337.4)


@pytest.fixture(scope="module")
def conn():
    from blockplan_db.connection import connect

    with connect() as c:
        yield c


@pytest.fixture(scope="module")
def rows(conn):
    return {r.table: r for r in verify.verify_rows(conn)}


@pytest.fixture(scope="module")
def exported(conn, tmp_path_factory):
    """The snapshot written back out as a CSV tree, in source-file order."""
    dest = str(tmp_path_factory.mktemp("file-order"))
    verify.export_snapshot(conn, dest, order=verify.FILE)
    return dest


# -- level 1: rows ----------------------------------------------------------

def test_every_table_is_present(rows):
    assert len(rows) == EXPECTED_TABLES


def test_the_whole_dataset_is_in_the_database(rows):
    assert sum(r.rows for r in rows.values()) == EXPECTED_ROWS


def test_every_table_matches_its_source_file(rows):
    """Compared as multisets: train_stops and movements have no natural key and
    repeat their train numbers, so a positional comparison pairs rows
    arbitrarily and reports thousands of differences that are not there."""
    differing = {t: (r.only_in_db, r.only_in_csv)
                 for t, r in rows.items() if not r.identical}
    assert not differing, f"tables differing from their source CSV: {differing}"


# -- the round trip back out ------------------------------------------------

def _rows_of(path: str) -> list[list[str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.reader(f))


@pytest.mark.parametrize("relative,source", [
    ("processed/sections.csv", paths.SECTIONS_CSV),
    ("processed/stations.csv", paths.STATIONS_CSV),
    ("processed/movements.csv", paths.MOVEMENTS_CSV),
    ("processed/pairing_rules.csv", paths.PAIRING_RULES_CSV),
    ("scenarios/scenarios.csv", paths.SCENARIOS_CSV),
])
def test_export_reproduces_the_source_file_exactly(exported, relative, source):
    """Ordered by row_no, every planning input comes back character for
    character -- header, row order and cell text.

    Character equality is stronger than this project strictly needs (the plan
    is built from parsed values, and float text may legitimately re-render),
    but it holds for every one of these files, so it is asserted while it does:
    a weaker check would not notice a column silently swapping places.
    """
    assert _rows_of(os.path.join(exported, relative)) == _rows_of(source)


def test_scenario_job_files_come_back_intact(exported):
    for name in os.listdir(paths.SCENARIO_JOBS_DIR):
        if not name.endswith(".csv"):
            continue
        got = os.path.join(exported, "scenarios", "jobs", name)
        assert _rows_of(got) == _rows_of(os.path.join(paths.SCENARIO_JOBS_DIR, name)), name


def test_pointing_the_loaders_elsewhere_puts_every_path_back(tmp_path):
    """dataset_root mutates module state. If it leaked, every later test in the
    process would silently plan from a temporary directory."""
    before = {n: getattr(paths, n) for n in dir(paths) if n.isupper()}
    with verify.dataset_root(str(tmp_path)):
        assert paths.SECTIONS_CSV.startswith(str(tmp_path))
    assert {n: getattr(paths, n) for n in dir(paths) if n.isupper()} == before


# -- level 2: the plan ------------------------------------------------------

@pytest.mark.slow
def test_the_database_rebuilds_the_reference_plan_exactly(conn):
    """The gate. Not "a plan with the same headline numbers" -- the same 140
    blocks, each with the same section, day, window, job set and unrounded
    reliability. The instance is degenerate enough that matching aggregates
    would prove very little on its own.
    """
    result = verify.verify_plan(conn, order=verify.FILE, expected=REFERENCE)
    assert result.got.plan_id == REFERENCE.plan_id
    assert result.got.objective == REFERENCE.objective
    assert result.got.blocks == REFERENCE.blocks
    assert result.got.fingerprint == REFERENCE.fingerprint, (
        "the plan built from PostgreSQL is not the plan built from the CSVs.\n"
        f"  expected {REFERENCE}\n  got      {result.got}"
    )


@pytest.mark.slow
def test_row_order_is_load_bearing(conn):
    """Why row_no exists, kept as a live measurement rather than a comment.

    blockplan_adapter.load_trains() builds each Train id as
    f"{train_number}#{i}" from the row's position in movements.csv, so file
    order reaches the optimiser. Read the same 2,978 rows back sorted by their
    natural key instead and every headline figure survives -- traffic cost,
    expected overrun, column count -- while the plan itself does not.

    If this ever fails, ordering has stopped mattering. That would be good
    news, and it should be confirmed deliberately before row_no is dropped:
    delete this test with a note rather than loosening it.
    """
    result = verify.verify_plan(conn, order=verify.KEYED, expected=REFERENCE)
    assert result.got.plan_id == REFERENCE.plan_id, "the request did not change"
    assert result.got.fingerprint != REFERENCE.fingerprint, (
        "reading the tables in natural-key order now reproduces the reference "
        "plan. Ordering may no longer be load-bearing -- confirm before relying "
        "on it."
    )
