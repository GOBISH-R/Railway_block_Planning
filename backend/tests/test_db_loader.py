"""Loader fidelity: every value that goes in is the value the CSV holds.

No database is contacted. Building the rows is a pure function of the frozen
CSVs, and that is where a transfer mistake would happen -- a column mapped to
the wrong name, a blank turned into a zero, a float reformatted -- so that is
what these cover.

The central test walks every cell of all 16,189 rows and compares the built
value back against the source text. It is exhaustive on purpose: a spot check
would pass while one column of one table quietly changed meaning.
"""
from __future__ import annotations

import csv
import json

import pytest

from blockplan_db import loader

EXPECTED_ROWS = {
    "stations": 27, "sections": 52, "trains": 108, "train_stops": 2736,
    "movements": 2978, "activities": 18, "pairing_rules": 6, "resources": 7,
    "jobs": 175, "block_requests": 175, "scenario_jobs": 1673,
    "execution": 5250, "execution_companions": 1890, "scenarios": 8,
    "scenario_jobs_manifest": 8, "method_comparison": 6,
    "benchmark_results": 8, "execution_scoring_summary": 6,
    "execution_scoring_blocks": 869, "data_dictionary": 113,
    "data_provenance": 76,
}


@pytest.fixture(scope="module")
def loads() -> dict[str, loader.TableLoad]:
    return {load.table: load for load in loader.build_all()}


def read_csv(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# -- shape ------------------------------------------------------------------

def test_every_expected_table_is_built(loads):
    assert set(loads) == set(EXPECTED_ROWS)


@pytest.mark.parametrize("table,expected", sorted(EXPECTED_ROWS.items()))
def test_row_counts_match_the_source_files(loads, table, expected):
    assert loads[table].row_count == expected


def test_the_whole_dataset_is_accounted_for(loads):
    assert sum(l.row_count for l in loads.values()) == 16189


def test_every_row_carries_the_snapshot_id(loads):
    for table, load in loads.items():
        idx = load.columns.index("snapshot_id")
        assert {row[idx] for row in load.rows} == {loader.FROZEN_SNAPSHOT_ID}, table


# -- the fidelity proof -----------------------------------------------------

@pytest.mark.parametrize("spec", loader.TABLES, ids=lambda s: s.table)
def test_every_cell_round_trips_from_its_source_file(spec, loads):
    """Compare each built value back against the CSV text it came from.

    Text must be identical characters. Numbers must equal float()/int() of the
    same cell -- the conversion the existing CSV loaders already perform, so
    the database path and the file path produce the same value.
    """
    load = loads[spec.table]
    source = read_csv(spec.source)
    assert len(source) == load.row_count

    for row_in, row_out in zip(source, load.rows):
        for header, db_col, kind in spec.columns:
            got = row_out[load.columns.index(db_col)]
            raw = row_in[header]
            if kind == loader.TEXT:
                assert got == raw, f"{spec.table}.{db_col}: {got!r} != {raw!r}"
            elif raw == "":
                assert got is None, f"{spec.table}.{db_col}: blank became {got!r}"
            elif kind == loader.INT:
                assert got == int(raw)
            else:
                assert got == float(raw)
                # repr equality: catches a value that compares equal but was
                # rounded or re-parsed on the way through.
                assert repr(got) == repr(float(raw))


def test_scenario_jobs_round_trip_and_carry_their_scenario(loads):
    load = loads["scenario_jobs"]
    scen_idx = load.columns.index("scenario")
    scenarios = [r["scenario"] for r in read_csv(loader.paths.SCENARIOS_CSV)]
    assert {row[scen_idx] for row in load.rows} == set(scenarios)

    seen = 0
    for scenario in scenarios:
        path = loader._p(
            loader.paths.SCENARIO_JOBS_DIR,
            loader.SCENARIO_JOB_FILES.format(scenario=scenario))
        source = read_csv(path)
        rows = [r for r in load.rows if r[scen_idx] == scenario]
        assert len(rows) == len(source), scenario
        for row_in, row_out in zip(source, rows):
            for header, db_col, kind in loader._JOB_COLUMNS:
                got = row_out[load.columns.index(db_col)]
                raw = row_in[header]
                if kind == loader.TEXT:
                    assert got == raw
                elif raw == "":
                    assert got is None
                else:
                    assert repr(got) == repr(float(raw) if kind == loader.REAL
                                             else int(raw))
        seen += len(rows)
    assert seen == 1673


# -- the specific traps found while inspecting the data ---------------------

def test_shouted_csv_headers_map_to_lower_case_columns(loads):
    """needs_T in the file, needs_t in the schema. Mapped, not guessed."""
    for table in ("jobs", "activities", "scenario_jobs"):
        cols = loads[table].columns
        for c in ("needs_t", "needs_p", "needs_d"):
            assert c in cols, f"{table} missing {c}"
        assert "needs_T" not in cols


def test_is_synthetic_stays_the_text_it_is(loads):
    """trains/movements hold "True"/"False", not 0/1. Stored as written."""
    for table in ("trains", "movements"):
        load = loads[table]
        values = {row[load.columns.index("is_synthetic")] for row in load.rows}
        assert values <= {"True", "False"}, f"{table}: {values}"


def test_blank_scenario_fields_become_null_not_zero(loads):
    """The adapter reads blank as a documented default; a zero would erase
    that distinction, and both columns are blank for most scenarios."""
    load = loads["scenarios"]
    source = read_csv(loader.paths.SCENARIOS_CSV)
    for col in ("extra_passenger_scale", "cancel_window_fraction"):
        idx = load.columns.index(col)
        blanks = sum(1 for r in source if r[col] == "")
        assert blanks > 0, f"{col} has no blanks -- test no longer meaningful"
        assert sum(1 for r in load.rows if r[idx] is None) == blanks


def test_the_eighteen_decimal_value_survives_intact(loads):
    """benchmark_results.enum_seconds holds 0.004162250999797834. It is stored
    as TEXT inside row_data precisely so nothing can truncate it."""
    load = loads["benchmark_results"]
    idx = load.columns.index("row_data")
    source = read_csv(loader.paths.BENCHMARK_RESULTS_CSV)
    for row_in, row_out in zip(source, load.rows):
        assert json.loads(row_out[idx])["enum_seconds"] == row_in["enum_seconds"]


def test_evidence_values_are_stored_as_their_original_characters(loads):
    """method_comparison is rendered verbatim on the Evidence screen."""
    load = loads["method_comparison"]
    source = read_csv(loader.paths.METHOD_COMPARISON_CSV)
    for row_in, row_out in zip(source, load.rows):
        for col in ("traffic_cost", "min_reliability", "cross_dept_share"):
            assert row_out[load.columns.index(col)] == row_in[col]
    # and the authoritative B4 row is still exactly what the CSV says
    b4 = next(r for r in load.rows
              if r[load.columns.index("method")].startswith("B4"))
    assert b4[load.columns.index("blocks")] == "138"
    assert b4[load.columns.index("traffic_cost")] == "272.8"


def test_json_tables_keep_every_field_of_the_original_row(loads):
    for table, source, _ in loader.JSON_TABLES:
        load = loads[table]
        idx = load.columns.index("row_data")
        rows_in = read_csv(source)
        for row_in, row_out in zip(rows_in, load.rows):
            assert json.loads(row_out[idx]) == row_in, table


def test_row_order_is_preserved_for_display(loads):
    """row_no drives the order the Evidence screen renders. Off-by-one here
    would reorder a published table."""
    for table in ("method_comparison", "benchmark_results",
                  "execution_scoring_summary"):
        load = loads[table]
        idx = load.columns.index("row_no")
        assert [r[idx] for r in load.rows] == list(range(1, load.row_count + 1))


# -- the snapshot record ----------------------------------------------------

def test_snapshot_row_carries_the_manifest_provenance():
    (sid, label, seed, version, hashes, notice, frozen) = loader.snapshot_metadata()
    assert sid == 1 and frozen is True
    assert seed == 42
    assert version
    assert set(json.loads(hashes)) == {"stations.json", "trains.json", "schedules.json"}
    # The notice must travel with the data it describes.
    assert "SYNTHETIC" in notice
    assert "not Indian Railways maintenance data" in notice
    assert label
