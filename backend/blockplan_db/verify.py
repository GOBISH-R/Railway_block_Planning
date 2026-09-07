"""Prove the database is a faithful substitute for the frozen CSVs.

Two levels, because the first is necessary and not sufficient.

LEVEL 1 -- rows. Every cell in the database equals the cell in the CSV it came
from. Compared as multisets, not positionally: `movements` and `train_stops`
have no key and repeat their train numbers, so an ordered comparison pairs rows
arbitrarily and reports thousands of differences that are not there. That
mistake was made once while building this; the multiset form is the correction.

LEVEL 2 -- the plan. Values can survive a round trip intact and still arrive in
a different ORDER, and order matters here: core.py's own comments record that an
unordered set of strings made constraints arrive differently between runs and
moved the plan. So this level runs the real pipeline over data that came out of
the database and compares the concrete plan -- the same fingerprint
tests/test_reference_plan.py pins.

It works by materialising the snapshot back to a CSV tree -- through
blockplan_db/repository.py, the same code the running service uses -- and
planning from it. The round trip is the point: CSV -> database -> CSV ->
planner. Nothing new sits in the path to be wrong, so a difference can only
have come from the database.

Level 2 runs under two ORDER BY clauses, because "does the plan survive?" and
"does the plan survive ANY deterministic read order?" are different questions
and Phase 4 depends on the answer to the second:

  FILE   ORDER BY row_no -- the source file's own order. This is the one that
         must reproduce the reference plan, and does.
  KEYED  ORDER BY each table's natural key: the ordering a repository layer
         would reach for by default. This does NOT reproduce it. Kept as a
         standing demonstration that row order is load-bearing, so nobody
         removes row_no later on the reasonable-sounding grounds that a natural
         key would do just as well.

TWO PROCESSES, NOT ONE. Each solve runs in a fresh subprocess, and that is not
tidiness. PlanningContext.load() captures core.RNG's state at load time and
calls it pristine (context.py:180); planner.py:253 resets the RNG to it before
each solve. The FIRST load in a process captures a genuinely untouched RNG. A
second one captures whatever the previous solve left behind, so it plans from a
different Monte Carlo stream. Measured: planning twice in one process from a
byte-identical copy of the frozen tree gives 337.4/140 blocks then 340.5/135.
Running both in one process here would have compared the database against that
artefact instead of against the dataset. It did, once.

This is a constraint on test and tool code, not a defect in the service, which
constructs exactly one PlanningService at startup.

    python -m blockplan_db.verify              # both levels
    python -m blockplan_db.verify --rows-only  # skip the solves
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from typing import Any, Sequence

from blockplan_service import paths

from . import loader, repository
from .repository import FILE, KEYED

REFERENCE_SCENARIO = "NORMAL_TRAFFIC"


# -- level 1: rows ----------------------------------------------------------

@dataclass(frozen=True)
class TableResult:
    table: str
    rows: int
    identical: bool
    only_in_db: int = 0
    only_in_csv: int = 0

    @property
    def status(self) -> str:
        return "identical" if self.identical else "DIFFERS"


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _convert(raw: str, kind: str) -> Any:
    return loader.CONVERT[kind](raw)


def _scenario_names() -> list[str]:
    return [r["scenario"] for r in _read_csv(paths.SCENARIOS_CSV)]


def _scenario_jobs_path(scenario: str) -> str:
    return os.path.join(paths.SCENARIO_JOBS_DIR,
                        loader.SCENARIO_JOB_FILES.format(scenario=scenario))


def verify_rows(conn, snapshot_id: int = loader.FROZEN_SNAPSHOT_ID) -> list[TableResult]:
    """All 21 tables, each compared as a bag of rows against its source file."""
    results: list[TableResult] = []

    for spec in loader.TABLES:
        cols = [db for _, db, _ in spec.columns]
        in_db = Counter(conn.execute(
            f"SELECT {', '.join(cols)} FROM {spec.table} WHERE snapshot_id = %s",
            (snapshot_id,)).fetchall())
        in_csv = Counter(
            tuple(_convert(row[h], k) for h, _, k in spec.columns)
            for row in _read_csv(spec.source))
        results.append(TableResult(
            spec.table, sum(in_csv.values()), in_db == in_csv,
            sum((in_db - in_csv).values()), sum((in_csv - in_db).values())))

    # scenario_jobs: eight files folded into one table, keyed by scenario.
    job_cols = [db for _, db, _ in loader._JOB_COLUMNS]
    in_db = Counter(conn.execute(
        f"SELECT scenario, {', '.join(job_cols)} FROM scenario_jobs "
        "WHERE snapshot_id = %s", (snapshot_id,)).fetchall())
    in_csv: Counter = Counter()
    for scenario in _scenario_names():
        for job in _read_csv(_scenario_jobs_path(scenario)):
            in_csv[(scenario,) + tuple(_convert(job[h], k)
                                       for h, _, k in loader._JOB_COLUMNS)] += 1
    results.append(TableResult(
        "scenario_jobs", sum(in_csv.values()), in_db == in_csv,
        sum((in_db - in_csv).values()), sum((in_csv - in_db).values())))

    # JSON tables carry row_no, so file order was recorded and can be compared
    # positionally -- stricter than a multiset, and worth having where it exists.
    for table, source, _ in loader.JSON_TABLES:
        docs = [r[0] for r in conn.execute(
            f"SELECT row_data FROM {table} WHERE snapshot_id = %s ORDER BY row_no",
            (snapshot_id,)).fetchall()]
        rows_in = _read_csv(source)
        results.append(TableResult(table, len(rows_in), docs == rows_in))

    return results


# -- level 2: the plan ------------------------------------------------------

@dataclass(frozen=True)
class Plan:
    plan_id: str
    fingerprint: str
    blocks: int
    objective: float

    def __str__(self) -> str:
        return (f"plan_id {self.plan_id}  obj {self.objective}  "
                f"{self.blocks} blocks  {self.fingerprint[:16]}...")


def _solve_here(scenario: str, root: str | None = None) -> Plan:
    """Solve against the tree at `root`, or the frozen one.

    Only ever called as the first solve in a fresh process -- see the module
    docstring on why a second one in the same process measures something else.

    Since Phase 4 this needs no trickery: PlanningContext.load() takes the tree
    to read. It used to swap the module-level path constants and put them back.
    """
    from blockplan_service import PlanningContext, PlanRequest, PlanningService

    source = paths.DatasetTree(root) if root else paths.FROZEN_TREE
    service = PlanningService(context=PlanningContext.load(source))
    plan = service.plan(
        PlanRequest(scenario=scenario, horizon_days=14, theta=0.90,
                    max_bundle_size=5, mc_samples=1500, seed=None),
        use_cache=False)
    internals = service.internals(plan["plan_id"])

    parts = []
    for block_id, column in internals.blocks_by_id.items():
        window = column.window
        parts.append("|".join([
            block_id, window.section_id, str(window.day), str(window.start_min),
            str(window.length), str(window.end_min), ",".join(column.job_ids),
            repr(column.reliability), repr(column.exp_overrun_cost),
            repr(window.traffic_cost)]))
    return Plan(plan["plan_id"],
                hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest(),
                len(parts), plan["objective"])


def plan_fingerprint(root: str | None = None,
                     scenario: str = REFERENCE_SCENARIO) -> Plan:
    """Solve in a FRESH PROCESS against `root`, or the frozen tree if None.

    The subprocess is the whole point; see the module docstring. Reuses this
    module as the entry point (`--solve`) so there is no second script to keep
    in step with the fingerprint definition.
    """
    cmd = [sys.executable, "-m", "blockplan_db.verify", "--solve", scenario]
    if root:
        cmd += ["--root", root]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=os.path.dirname(os.path.dirname(
                              os.path.abspath(__file__))))
    if proc.returncode != 0:
        raise RuntimeError(f"solve subprocess failed:\n{proc.stderr[-4000:]}")
    return Plan(**json.loads(proc.stdout.strip().splitlines()[-1]))


@dataclass(frozen=True)
class PlanResult:
    order: str
    got: Plan
    expected: Plan

    @property
    def identical(self) -> bool:
        return (self.got.plan_id == self.expected.plan_id
                and self.got.fingerprint == self.expected.fingerprint)

    @property
    def status(self) -> str:
        return "identical" if self.identical else "DIFFERS"


def verify_plan(conn, *, order: str = FILE, expected: Plan | None = None,
                snapshot_id: int = loader.FROZEN_SNAPSHOT_ID) -> PlanResult:
    """Export the snapshot, plan from it, compare against the plan from the CSVs.

    `expected` omitted means solve the frozen tree too -- correct, and twice
    as slow.
    """
    if expected is None:
        expected = plan_fingerprint()
    with tempfile.TemporaryDirectory(prefix="blockplan-verify-") as tmp:
        repository.materialise(conn, tmp, snapshot_id=snapshot_id, order=order)
        got = plan_fingerprint(tmp)
    return PlanResult(order, got, expected)


# -- report -----------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify the database reproduces the frozen dataset.")
    ap.add_argument("--rows-only", action="store_true",
                    help="skip the plan comparison, which runs real solves")
    ap.add_argument("--solve", metavar="SCENARIO",
                    help=argparse.SUPPRESS)   # internal: the subprocess worker
    ap.add_argument("--root", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.solve:
        print(json.dumps(dataclasses.asdict(_solve_here(args.solve, args.root))))
        return 0

    from .connection import connect, database_url

    print(f"target: {database_url()}\n")
    failures = 0

    with connect() as conn:
        print("LEVEL 1 -- rows")
        total = 0
        for result in verify_rows(conn):
            total += result.rows
            detail = ("" if result.identical else
                      f"  db-only={result.only_in_db} csv-only={result.only_in_csv}")
            print(f"  {result.table:28} {result.rows:6d}  {result.status}{detail}")
            failures += 0 if result.identical else 1
        print(f"  {'TOTAL':28} {total:6d}")

        if args.rows_only:
            print("\n(plan comparison skipped)")
            return 0 if failures == 0 else 1

        print("\nLEVEL 2 -- the plan  (each solve in its own process)")
        print("  frozen CSVs ...", flush=True)
        expected = plan_fingerprint()
        print(f"    {expected}")

        print(f"  database, {FILE} order (ORDER BY row_no) ...", flush=True)
        result = verify_plan(conn, order=FILE, expected=expected)
        print(f"    {result.got}  {result.status}")
        failures += 0 if result.identical else 1

        print(f"  database, {KEYED} order (natural keys) ...", flush=True)
        keyed = verify_plan(conn, order=KEYED, expected=expected)
        print(f"    {keyed.got}  {keyed.status}")
        if keyed.identical:
            print("    NOTE: ordering no longer changes the plan. row_no may now"
                  " be redundant;\n          confirm deliberately before relying"
                  " on that.")
        else:
            print("    expected: this is why row_no exists.")

    print(f"\nRESULT: {'VERIFIED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
