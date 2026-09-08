"""Prove the ingestion adapter is faithful: feed in, reference plan out.

    python -m blockplan_ingest.verify
    python -m blockplan_ingest.verify --keep <dir>    # leave the feed behind

The round trip is the whole argument. Export the frozen dataset INTO feed
format, ingest it back through the real adapter, plan, and require the concrete
reference plan -- plan_id 2db53586d84f, objective 337.4, and the sha256 over all
140 blocks that tests/test_reference_plan.py pins.

Without an inverse, an adapter can only ever be tested against data invented to
suit it, which tests the invention. With one, the input is the frozen dataset
that every published figure came from, so a mapping error has nowhere to hide:
a wrong protection flag, a lost resource allocation, a mis-derived truncation
bound all move the plan.

Two of those were caught exactly this way while building it. Deriving the
duration bounds as mean +/- 3 sigma gave 6 and 50.4 minutes where the catalogue
says 18 and 65. Defaulting every resource to instance 0 made 110 of 175 jobs
mutually exclusive, because core.py:287 refuses to bundle jobs that share one.

THE SOLVE RUNS IN A FRESH PROCESS, for the reason blockplan_db/verify.py
documents: PlanningContext.load() captures core.RNG's state and calls it
pristine, so only the first load in a process is genuinely pristine.
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
from dataclasses import dataclass

from blockplan_service import paths

from . import feeds
from .datasource import materialise

REFERENCE_PLAN_ID = "2db53586d84f"
REFERENCE_FINGERPRINT = (
    "6f509bae39c8a032ce99201370b8c8522734a0b247f56bc4d61dcc894600b429"
)
REFERENCE_SCENARIO = "NORMAL_TRAFFIC"


@dataclass(frozen=True)
class Plan:
    plan_id: str
    fingerprint: str
    blocks: int
    objective: float

    @property
    def matches_reference(self) -> bool:
        return (self.plan_id == REFERENCE_PLAN_ID
                and self.fingerprint == REFERENCE_FINGERPRINT)

    def __str__(self) -> str:
        return (f"plan_id {self.plan_id}  obj {self.objective}  "
                f"{self.blocks} blocks  {self.fingerprint[:16]}...")


def export_frozen_feed(destination: str) -> dict[str, str]:
    """The frozen jobs, written out as TMS/SMMS/TDMS work orders."""
    with open(os.path.join(paths.PROCESSED_DIR, "jobs.csv"), encoding="utf-8") as f:
        job_rows = list(csv.DictReader(f))
    return feeds.write_feed_directory(
        feeds.demand_to_feed_records(job_rows), destination)


def _solve_here(root: str | None) -> Plan:
    """One solve, first thing in a fresh process."""
    from blockplan_service import PlanningContext, PlanningService, PlanRequest

    source = paths.DatasetTree(root) if root else paths.FROZEN_TREE
    service = PlanningService(context=PlanningContext.load(source))
    plan = service.plan(
        PlanRequest(scenario=REFERENCE_SCENARIO, horizon_days=14, theta=0.90,
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


def plan_from(root: str) -> Plan:
    """Solve against a materialised tree, in a subprocess."""
    proc = subprocess.run(
        [sys.executable, "-m", "blockplan_ingest.verify", "--solve", "--root", root],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if proc.returncode != 0:
        raise RuntimeError(f"solve subprocess failed:\n{proc.stderr[-4000:]}")
    return Plan(**json.loads(proc.stdout.strip().splitlines()[-1]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify the TMS/SMMS/TDMS adapter reproduces the frozen plan.")
    ap.add_argument("--keep", help="write the generated feed here and leave it")
    ap.add_argument("--solve", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--root", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.solve:
        print(json.dumps(dataclasses.asdict(_solve_here(args.root))))
        return 0

    workspace = args.keep or tempfile.mkdtemp(prefix="blockplan-ingest-verify-")
    feed_dir = os.path.join(workspace, "feed")
    tree_dir = os.path.join(workspace, "tree")

    print("exporting the frozen dataset as TMS/SMMS/TDMS work orders...")
    written = export_frozen_feed(feed_dir)
    for system, path in written.items():
        with open(path, encoding="utf-8") as f:
            count = len(json.load(f)["work_orders"])
        print(f"  {system:5} {count:4d} work orders -> {os.path.basename(path)}")

    print("\ningesting them back through the adapter...")
    tree, validation = materialise(feed_dir, tree_dir)
    print(f"  {validation.summary()}")
    if validation.rejected:
        for work_order, reason in validation.rejected[:5]:
            print(f"  REJECTED {work_order}: {reason}")

    print("\nplanning (fresh process)...")
    plan = plan_from(tree.root)
    print(f"  {plan}")
    print(f"  expected plan_id {REFERENCE_PLAN_ID}, "
          f"fingerprint {REFERENCE_FINGERPRINT[:16]}...")

    ok = plan.matches_reference and not validation.rejected
    print(f"\nRESULT: {'VERIFIED' if ok else 'DIFFERS'}")
    if args.keep:
        print(f"feed and tree left in {workspace}")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
