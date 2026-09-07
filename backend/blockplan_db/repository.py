"""Read a snapshot back out of PostgreSQL as a dataset tree.

This is the read half of the database layer, and it materialises: it writes the
snapshot's planning inputs to a directory and hands back a `DatasetTree`. It
does not stream rows into domain objects.

That is a deliberate choice, not a shortcut. The blockplan_adapter loaders take
file paths and open() them, and CLAUDE.md requires reusing them verbatim rather
than reimplementing the parsing they do -- `load_trains`, for one, derives each
Train id from the row's position in the file, and a reimplementation that
missed that would silently change the plan. Materialising keeps those loaders
on the only input they accept, so the database path and the CSV path run
through identical code.

The cost is one directory written at startup, a few megabytes, once. What it
buys is that "reading from PostgreSQL" is provably the same operation as
reading from disk: Phase 3 measured the tree this writes as character-for-
character identical to the frozen one, producing the same plan_id, objective
and 140-block fingerprint (blockplan_db/verify.py, tests/test_db_verify.py).

ORDER BY row_no, always. Row order reaches the optimiser through
load_trains(); ordering by a natural key instead reproduces every headline
figure and still returns a different plan. See the ROW ORDER note in
schema.sql.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Any, Sequence

from blockplan_service.paths import DatasetTree

from . import loader

# Read order. FILE is the only one production uses; KEYED exists so
# verify.py can demonstrate that it is not good enough.
FILE = "file"
KEYED = "keyed"

#: The natural key each table would be ordered by if row_no did not exist.
KEY_ORDER = {
    "stations": "seq",
    "sections": "section_id",
    "pairing_rules": "activity, companion_activity",
    "movements": "train_number, enter_min, from_code, to_code, direction",
    "scenarios": "scenario",
    "scenario_jobs": "job_id",
}

#: table -> path within the tree. The six inputs a PlanningContext reads.
LAYOUT = {
    "sections": ("processed", "sections.csv"),
    "stations": ("processed", "stations.csv"),
    "movements": ("processed", "movements.csv"),
    "pairing_rules": ("processed", "pairing_rules.csv"),
    "scenarios": ("scenarios", "scenarios.csv"),
}


class SnapshotNotFoundError(LookupError):
    """The requested snapshot is not in the database."""


@dataclass(frozen=True)
class SnapshotInfo:
    """What a snapshot says about itself, for /health and for provenance."""

    snapshot_id: int
    label: str
    seed: int | None
    generator_version: str | None
    is_frozen: bool
    created_at: Any
    notice: str

    def describe(self) -> str:
        frozen = "frozen" if self.is_frozen else "mutable"
        return f"snapshot {self.snapshot_id} ({self.label}, {frozen})"


def read_snapshot_info(conn, snapshot_id: int = loader.FROZEN_SNAPSHOT_ID) -> SnapshotInfo:
    row = conn.execute(
        "SELECT snapshot_id, label, seed, generator_version, is_frozen, "
        "created_at, notice FROM dataset_snapshots WHERE snapshot_id = %s",
        (snapshot_id,)).fetchone()
    if row is None:
        raise SnapshotNotFoundError(
            f"snapshot {snapshot_id} is not in this database. Load it with "
            "`python -m blockplan_db.loader`.")
    return SnapshotInfo(*row)


def _as_cell(value: Any) -> str:
    """A value back into a CSV cell.

    repr() of a float is the shortest string that parses back to the same
    double, so an exported cell can differ from the original character for
    character while producing an identical value when the loader reads it.
    Measured on this dataset: none of them do -- every planning input comes
    back byte for byte (tests/test_db_verify.py).
    """
    return "" if value is None else str(value)


def materialise(conn, dest: str, *, snapshot_id: int = loader.FROZEN_SNAPSHOT_ID,
                order: str = FILE) -> DatasetTree:
    """Write a snapshot's planning inputs to `dest` and return the tree.

    `order` is FILE in production. KEYED is for verification only: it reads the
    same rows in natural-key order to demonstrate that doing so changes the
    plan.
    """
    read_snapshot_info(conn, snapshot_id)      # fail early and by name

    tree = DatasetTree(dest)
    for directory in (tree.processed_dir, tree.scenarios_dir, tree.scenario_jobs_dir):
        os.makedirs(directory, exist_ok=True)

    def write(path: str, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows([_as_cell(v) for v in row] for row in rows)

    by_table = {spec.table: spec for spec in loader.TABLES}
    for table, (subdir, filename) in LAYOUT.items():
        spec = by_table[table]
        clause = "row_no" if order == FILE else KEY_ORDER[table]
        write(os.path.join(tree.root, subdir, filename),
              [h for h, _, _ in spec.columns],
              conn.execute(
                  f"SELECT {', '.join(db for _, db, _ in spec.columns)} "
                  f"FROM {spec.table} WHERE snapshot_id = %s ORDER BY {clause}",
                  (snapshot_id,)).fetchall())

    headers = [h for h, _, _ in loader._JOB_COLUMNS]
    cols = ", ".join(db for _, db, _ in loader._JOB_COLUMNS)
    clause = "row_no" if order == FILE else KEY_ORDER["scenario_jobs"]
    for (scenario,) in conn.execute(
            "SELECT scenario FROM scenarios WHERE snapshot_id = %s ORDER BY row_no",
            (snapshot_id,)).fetchall():
        write(tree.scenario_jobs_csv(scenario), headers, conn.execute(
            f"SELECT {cols} FROM scenario_jobs WHERE snapshot_id = %s "
            f"AND scenario = %s ORDER BY {clause}",
            (snapshot_id, scenario)).fetchall())

    missing = tree.missing()
    if missing:
        raise RuntimeError(f"materialised tree is incomplete: {missing}")
    return tree
