"""Load the frozen dataset into PostgreSQL as snapshot 1.

The job is transfer, not transformation. Every value that goes in must be the
value that comes out, because every number this project quotes was produced
from these rows. So the loader does the least possible: it reads each CSV,
converts a cell only where the schema is typed, and writes it.

Structured so that almost all of it can be tested without a database. Building
the rows is a pure function of the CSV files -- that is where a fidelity
mistake would happen, so that is the part with tests. Insertion is a thin
wrapper around executemany.

Two conversion rules, and they are the whole fidelity story:

  * TEXT columns are stored verbatim, including empty strings. An empty string
    is not NULL; conflating them would change what comes back.
  * INTEGER and DOUBLE PRECISION columns take NULL for a blank cell, and
    int()/float() otherwise -- exactly what the CSV loaders already do when
    they read the same file. Verified: every value in the dataset round-trips
    through float() unchanged.

Run with:
    python -m blockplan_db.loader              # load snapshot 1
    python -m blockplan_db.loader --dry-run    # build rows, print counts, exit
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from blockplan_service import paths

FROZEN_SNAPSHOT_ID = 1
FROZEN_SNAPSHOT_LABEL = "frozen dataset (seed 42)"

METADATA_DIR = os.path.join(paths.DATASET_DIR, "metadata")

# -- cell conversion --------------------------------------------------------

TEXT = "text"
INT = "int"
REAL = "real"


def _as_text(value: str) -> str:
    """Verbatim. An empty cell stays an empty string, not NULL."""
    return value


def _as_int(value: str) -> int | None:
    return None if value == "" else int(value)


def _as_real(value: str) -> float | None:
    return None if value == "" else float(value)


CONVERT: dict[str, Callable[[str], Any]] = {
    TEXT: _as_text,
    INT: _as_int,
    REAL: _as_real,
}


# -- table specifications ---------------------------------------------------

@dataclass(frozen=True)
class TableSpec:
    """One CSV to one table.

    `columns` pairs the CSV header with the database column and its type. The
    two names differ where the CSV shouts (needs_T) and the schema does not
    (needs_t); listing both is what stops that mapping being guessed.
    """

    table: str
    source: str                                   # path to the CSV
    columns: Sequence[tuple[str, str, str]]       # (csv_header, db_column, type)
    extra: Sequence[str] = field(default_factory=tuple)   # db columns filled by the loader


def _p(*parts: str) -> str:
    return os.path.join(*parts)


_JOB_COLUMNS: Sequence[tuple[str, str, str]] = (
    ("job_id", "job_id", TEXT),
    ("dept", "dept", TEXT),
    ("activity", "activity", TEXT),
    ("section_id", "section_id", TEXT),
    ("location_desc", "location_desc", TEXT),
    ("km_from", "km_from", REAL),
    ("km_to", "km_to", REAL),
    ("needs_T", "needs_t", INT),
    ("needs_P", "needs_p", INT),
    ("needs_D", "needs_d", INT),
    ("needs_train_movements", "needs_train_movements", INT),
    ("needs_live_ohe", "needs_live_ohe", INT),
    ("duration_mean_min", "duration_mean_min", REAL),
    ("duration_sd_min", "duration_sd_min", REAL),
    ("duration_min_min", "duration_min_min", REAL),
    ("duration_max_min", "duration_max_min", REAL),
    ("min_block_min", "min_block_min", INT),
    ("resources", "resources", TEXT),
    ("due_day", "due_day", INT),
    ("criticality", "criticality", REAL),
    ("priority", "priority", TEXT),
    ("uncertainty_level", "uncertainty_level", TEXT),
    ("provenance", "provenance", TEXT),
)

TABLES: tuple[TableSpec, ...] = (
    TableSpec("stations", _p(paths.PROCESSED_DIR, "stations.csv"), (
        ("station_code", "station_code", TEXT), ("station_name", "station_name", TEXT),
        ("latitude", "latitude", REAL), ("longitude", "longitude", REAL),
        ("zone", "zone", TEXT), ("state", "state", TEXT),
        ("seq", "seq", INT), ("is_junction", "is_junction", INT))),

    TableSpec("sections", _p(paths.PROCESSED_DIR, "sections.csv"), (
        ("section_id", "section_id", TEXT),
        ("from_station_code", "from_station_code", TEXT),
        ("to_station_code", "to_station_code", TEXT), ("line", "line", TEXT),
        ("length_km", "length_km", REAL), ("tracks", "tracks", INT),
        ("electrified", "electrified", INT), ("is_single", "is_single", INT),
        ("headway_min", "headway_min", INT),
        ("degraded_factor", "degraded_factor", REAL),
        ("support_trains", "support_trains", INT),
        ("track_source", "track_source", TEXT))),

    # is_synthetic holds "True"/"False", not 0/1 -- stored as written.
    TableSpec("trains", _p(paths.PROCESSED_DIR, "trains.csv"), (
        ("train_number", "train_number", TEXT), ("train_name", "train_name", TEXT),
        ("train_class", "train_class", TEXT), ("is_synthetic", "is_synthetic", TEXT),
        ("direction", "direction", TEXT))),

    TableSpec("train_stops", _p(paths.PROCESSED_DIR, "train_stops.csv"), (
        ("train_number", "train_number", TEXT), ("train_name", "train_name", TEXT),
        ("station_code", "station_code", TEXT), ("arrival_min", "arrival_min", INT),
        ("departure_min", "departure_min", INT), ("day", "day", INT),
        ("stop_seq", "stop_seq", INT))),

    TableSpec("movements", _p(paths.PROCESSED_DIR, "movements.csv"), (
        ("train_number", "train_number", TEXT), ("train_class", "train_class", TEXT),
        ("from_code", "from_code", TEXT), ("to_code", "to_code", TEXT),
        ("direction", "direction", TEXT), ("enter_min", "enter_min", INT),
        ("is_synthetic", "is_synthetic", TEXT))),

    TableSpec("activities", _p(paths.PROCESSED_DIR, "activities.csv"), (
        ("activity_id", "activity_id", TEXT), ("dept", "dept", TEXT),
        ("label", "label", TEXT), ("asset", "asset", TEXT),
        ("needs_T", "needs_t", INT), ("needs_P", "needs_p", INT),
        ("needs_D", "needs_d", INT),
        ("needs_train_movements", "needs_train_movements", INT),
        ("needs_live_ohe", "needs_live_ohe", INT),
        ("duration_mean_min", "duration_mean_min", INT),
        ("duration_sd_min", "duration_sd_min", INT),
        ("periodicity_days", "periodicity_days", INT),
        ("min_block_min", "min_block_min", INT),
        ("min_block_provenance", "min_block_provenance", TEXT),
        ("resource_class", "resource_class", TEXT),
        ("criticality_base", "criticality_base", REAL),
        ("protection_source", "protection_source", TEXT))),

    TableSpec("pairing_rules", paths.PAIRING_RULES_CSV, (
        ("activity", "activity", TEXT), ("compelled_dept", "compelled_dept", TEXT),
        ("companion_activity", "companion_activity", TEXT),
        ("duration_mean_min", "duration_mean_min", INT),
        ("duration_sd_min", "duration_sd_min", INT),
        ("must_follow_parent", "must_follow_parent", INT),
        ("precedes_parent", "precedes_parent", INT),
        ("source", "source", TEXT), ("confidence", "confidence", REAL))),

    TableSpec("resources", _p(paths.PROCESSED_DIR, "resources.csv"), (
        ("resource_class", "resource_class", TEXT),
        ("fleet_size", "fleet_size", INT), ("provenance", "provenance", TEXT))),

    TableSpec("jobs", _p(paths.PROCESSED_DIR, "jobs.csv"), _JOB_COLUMNS),

    TableSpec("block_requests", _p(paths.PROCESSED_DIR, "block_requests.csv"), (
        ("request_id", "request_id", TEXT), ("job_id", "job_id", TEXT),
        ("department", "department", TEXT),
        ("preferred_date", "preferred_date", INT),
        ("preferred_window_start_min", "preferred_window_start_min", INT),
        ("minimum_duration_min", "minimum_duration_min", INT),
        ("requested_duration_min", "requested_duration_min", INT),
        ("protection_type", "protection_type", TEXT),
        ("deadline_day", "deadline_day", INT), ("priority", "priority", TEXT),
        ("reason", "reason", TEXT), ("provenance", "provenance", TEXT))),

    # extra_passenger_scale and cancel_window_fraction are blank for most
    # scenarios; the adapter reads blank as a documented default, so NULL keeps
    # that distinction where a zero would erase it.
    TableSpec("scenarios", paths.SCENARIOS_CSV, (
        ("scenario", "scenario", TEXT), ("demand_scale", "demand_scale", REAL),
        ("freight_scale", "freight_scale", REAL),
        ("uncertainty_scale", "uncertainty_scale", REAL),
        ("urgency_shift", "urgency_shift", INT), ("backlog", "backlog", REAL),
        ("extra_passenger_scale", "extra_passenger_scale", REAL),
        ("cancel_window_fraction", "cancel_window_fraction", REAL),
        ("note", "note", TEXT))),

    TableSpec("scenario_jobs_manifest",
              _p(paths.SCENARIOS_DIR, "scenario_jobs_manifest.csv"), (
        ("scenario", "scenario", TEXT), ("seed", "seed", INT),
        ("target_jobs", "target_jobs", INT),
        ("generated_jobs", "generated_jobs", INT),
        ("demand_scale", "demand_scale", REAL),
        ("backlog_multiplier", "backlog_multiplier", REAL),
        ("uncertainty_scale", "uncertainty_scale", REAL),
        ("urgency_shift", "urgency_shift", INT),
        ("jobs_ENGG", "jobs_engg", INT), ("jobs_SNT", "jobs_snt", INT),
        ("jobs_TRD", "jobs_trd", INT), ("overdue_jobs", "overdue_jobs", INT),
        ("file", "file", TEXT), ("method", "method", TEXT))),

    TableSpec("execution", _p(paths.PROCESSED_DIR, "execution.csv"), (
        ("realisation", "realisation", INT), ("job_id", "job_id", TEXT),
        ("actual_duration_min", "actual_duration_min", REAL))),

    TableSpec("execution_companions",
              _p(paths.PROCESSED_DIR, "execution_companions.csv"), (
        ("realisation", "realisation", INT), ("job_id", "job_id", TEXT),
        ("actual_duration_min", "actual_duration_min", REAL),
        ("parent_job_id", "parent_job_id", TEXT),
        ("provenance", "provenance", TEXT))),

    # Every column TEXT: these are rendered verbatim on the Evidence screen, so
    # they have to come back as the same characters.
    TableSpec("method_comparison", paths.METHOD_COMPARISON_CSV, (
        ("method", "method", TEXT), ("blocks", "blocks", TEXT),
        ("jobs_done", "jobs_done", TEXT), ("jobs_deferred", "jobs_deferred", TEXT),
        ("traffic_cost", "traffic_cost", TEXT),
        ("traffic_per_job", "traffic_per_job", TEXT),
        ("exp_overrun_cost", "exp_overrun_cost", TEXT),
        ("cross_dept_blocks", "cross_dept_blocks", TEXT),
        ("cross_dept_share", "cross_dept_share", TEXT),
        ("mean_reliability", "mean_reliability", TEXT),
        ("min_reliability", "min_reliability", TEXT),
        ("block_utilisation", "block_utilisation", TEXT)), extra=("row_no",)),
)

# Wide or metadata tables kept as JSONB of the original strings: a new CSV
# column must not require a schema change, and the row is reproduced exactly.
JSON_TABLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("benchmark_results", paths.BENCHMARK_RESULTS_CSV, ("scenario",)),
    ("execution_scoring_summary", paths.EXECUTION_SCORING_SUMMARY_CSV, ("method",)),
    ("execution_scoring_blocks",
     _p(paths.SCENARIOS_DIR, "execution_scoring_blocks.csv"), ()),
    ("data_dictionary", _p(METADATA_DIR, "DATA_DICTIONARY.csv"), ()),
    ("data_provenance", _p(METADATA_DIR, "DATA_PROVENANCE.csv"),
     ("table", "field", "classification")),
)

SCENARIO_JOB_FILES = "jobs_{scenario}.csv"


# -- row building (pure; no database) ---------------------------------------

@dataclass(frozen=True)
class TableLoad:
    table: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _build_typed(spec: TableSpec, snapshot_id: int) -> TableLoad:
    rows_in = _read_csv(spec.source)
    if rows_in:
        missing = [h for h, _, _ in spec.columns if h not in rows_in[0]]
        if missing:
            raise ValueError(f"{spec.table}: {spec.source} is missing {missing}")

    db_cols = ["snapshot_id"] + list(spec.extra) + [db for _, db, _ in spec.columns]
    out = []
    for i, row in enumerate(rows_in, start=1):
        values: list[Any] = [snapshot_id]
        if "row_no" in spec.extra:
            values.append(i)
        for header, _, kind in spec.columns:
            values.append(CONVERT[kind](row[header]))
        out.append(tuple(values))
    return TableLoad(spec.table, tuple(db_cols), tuple(out))


def _build_json(table: str, source: str, promoted: Sequence[str],
                snapshot_id: int) -> TableLoad:
    """Whole row as JSONB, with a few columns promoted for querying.

    Promoted columns are copies, not moves: row_data still holds every field,
    so nothing depends on which ones were chosen.
    """
    rows_in = _read_csv(source)
    db_cols = ["snapshot_id", "row_no"] + [
        "table_name" if c == "table" else c for c in promoted] + ["row_data"]
    out = []
    for i, row in enumerate(rows_in, start=1):
        values: list[Any] = [snapshot_id, i]
        values.extend(row.get(c) for c in promoted)
        values.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
        out.append(tuple(values))
    return TableLoad(table, tuple(db_cols), tuple(out))


def _build_scenario_jobs(snapshot_id: int) -> TableLoad:
    """The eight per-scenario job sets into one table, keyed by scenario.

    Verified: each file carries exactly jobs.csv's 23 columns, so the shared
    column list is reused rather than restated.
    """
    scenarios = [r["scenario"] for r in _read_csv(paths.SCENARIOS_CSV)]
    db_cols = ["snapshot_id", "scenario"] + [db for _, db, _ in _JOB_COLUMNS]
    out = []
    for scenario in scenarios:
        path = _p(paths.SCENARIO_JOBS_DIR, SCENARIO_JOB_FILES.format(scenario=scenario))
        for row in _read_csv(path):
            values: list[Any] = [snapshot_id, scenario]
            for header, _, kind in _JOB_COLUMNS:
                values.append(CONVERT[kind](row[header]))
            out.append(tuple(values))
    return TableLoad("scenario_jobs", tuple(db_cols), tuple(out))


def snapshot_metadata(snapshot_id: int = FROZEN_SNAPSHOT_ID) -> tuple[Any, ...]:
    """The snapshot row, taken from the dataset's own manifest.

    seed, generator_version, the three source hashes and the NOTICE are carried
    across so the snapshot can be checked against the files it claims to come
    from, and so the synthetic-data notice cannot be separated from the rows it
    describes.
    """
    with open(_p(METADATA_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    return (
        snapshot_id,
        FROZEN_SNAPSHOT_LABEL,
        manifest.get("seed"),
        str(manifest.get("generator_version", "")),
        json.dumps(manifest.get("source_hashes", {}), sort_keys=True),
        manifest["NOTICE"],
        True,      # is_frozen
    )


def build_all(snapshot_id: int = FROZEN_SNAPSHOT_ID) -> list[TableLoad]:
    """Every table, built from the CSVs. Pure: reads files, touches no database."""
    loads = [_build_typed(spec, snapshot_id) for spec in TABLES]
    loads.append(_build_scenario_jobs(snapshot_id))
    loads.extend(_build_json(t, src, promoted, snapshot_id)
                 for t, src, promoted in JSON_TABLES)
    return loads


# -- insertion --------------------------------------------------------------

def _insert(cur, load: TableLoad) -> None:
    cols = ", ".join(load.columns)
    marks = ", ".join(["%s"] * len(load.columns))
    cur.executemany(f"INSERT INTO {load.table} ({cols}) VALUES ({marks})", load.rows)


def apply_schema(conn) -> None:
    with open(_p(os.path.dirname(os.path.abspath(__file__)), "schema.sql"),
              encoding="utf-8") as f:
        conn.execute(f.read())


def load_snapshot(conn, snapshot_id: int = FROZEN_SNAPSHOT_ID,
                  *, replace: bool = False) -> list[TableLoad]:
    """Write the frozen dataset as one transaction.

    Refuses to overwrite a snapshot already marked frozen unless explicitly
    told to. Snapshot 1 is the provenance of every number this project quotes;
    rewriting it by accident is the one mistake this loader must not allow.
    """
    existing = conn.execute(
        "SELECT is_frozen FROM dataset_snapshots WHERE snapshot_id = %s",
        (snapshot_id,)).fetchone()
    if existing is not None:
        if existing[0] and not replace:
            raise RuntimeError(
                f"snapshot {snapshot_id} exists and is marked frozen. Loading "
                "again would rewrite the provenance of every published number. "
                "Pass replace=True only with a deliberate decision to do that.")
        conn.execute("DELETE FROM dataset_snapshots WHERE snapshot_id = %s",
                     (snapshot_id,))

    loads = build_all(snapshot_id)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO dataset_snapshots (snapshot_id, label, seed, "
            "generator_version, source_hashes, notice, is_frozen) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            snapshot_metadata(snapshot_id))
        for load in loads:
            _insert(cur, load)
    return loads


def _report(loads: Iterable[TableLoad]) -> int:
    total = 0
    for load in sorted(loads, key=lambda x: x.table):
        total += load.row_count
        print(f"  {load.table:28} {load.row_count:6d} rows  "
              f"{len(load.columns):2d} cols")
    print(f"  {'TOTAL':28} {total:6d} rows")
    return total


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Load the frozen dataset as snapshot 1.")
    ap.add_argument("--dry-run", action="store_true",
                    help="build every row from the CSVs and report, without connecting")
    ap.add_argument("--replace", action="store_true",
                    help="overwrite an existing frozen snapshot (deliberate re-baseline)")
    args = ap.parse_args(argv)

    if args.dry_run:
        print("Building rows from the frozen CSVs (no database contacted)")
        _report(build_all())
        return 0

    from .connection import connect, database_url

    print(f"target: {database_url()}")
    with connect() as conn:
        apply_schema(conn)
        loads = load_snapshot(conn, replace=args.replace)
        conn.commit()
    print("loaded snapshot 1:")
    _report(loads)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
