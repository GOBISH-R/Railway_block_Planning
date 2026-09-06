#!/usr/bin/env python3
"""Feed the generated dataset into the existing optimiser.

This is the Phase-16 answer. The audit found that core.py/demo.py/dense.py read
NO files at all: the CSVs shipped with the optimiser were exported FROM
hard-coded Python objects, never read back in. So nothing in the dataset
reached the solver.

This adapter closes that gap without rewriting core.py. It:

  1. loads config/*.yaml over core.py's module-level constants, so the policy
     parameters (theta, kappa, block lengths, train weights, closing chains,
     span limit, overrun rate) come from the dataset build rather than from
     literals in the source;
  2. loads pairing_rules.csv into core.MANDATORY_PAIRING, so the rule table is
     data and a division can edit a row;
  3. constructs core.Job / core.Section / core.Train from the dataset CSVs.

Run:  python blockplan_adapter.py --dataset ../dataset --core /path/to/blockplan
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import yaml


def load_config_into_core(core, config_dir):
    """Override core.py's hard-coded constants from the dataset configuration."""
    with open(os.path.join(config_dir, "assumptions.yaml")) as f:
        A = yaml.safe_load(f)
    with open(os.path.join(config_dir, "rules.yaml")) as f:
        R = yaml.safe_load(f)

    applied = {}
    core.THETA = A["reliability"]["theta"]; applied["THETA"] = core.THETA
    core.KAPPA = A["reliability"]["kappa"]; applied["KAPPA"] = core.KAPPA
    core.LAMBDA_CLOSE = A["reliability"]["lambda_close_min"]
    applied["LAMBDA_CLOSE"] = core.LAMBDA_CLOSE
    core.CLOSING = {k: (v["mean"], v["sd"])
                    for k, v in A["closing_chain_min"].items()}
    applied["CLOSING"] = core.CLOSING
    core.TRAIN_WEIGHT = dict(A["traffic"]["train_weight"])
    applied["TRAIN_WEIGHT"] = f"{len(core.TRAIN_WEIGHT)} classes"
    core.OVERRUN_RATE = A["traffic"]["overrun_rate"]
    applied["OVERRUN_RATE"] = core.OVERRUN_RATE
    core.MAX_SPAN_KM = A["bundling"]["max_span_km"]
    applied["MAX_SPAN_KM"] = core.MAX_SPAN_KM
    core.ALLOWED_BLOCK_LENGTHS = tuple(R["block_envelope"]["single_line"]["options_min"])
    applied["ALLOWED_BLOCK_LENGTHS"] = core.ALLOWED_BLOCK_LENGTHS
    core.EXCEPTIONAL_LENGTH = R["block_envelope"]["single_line"]["exceptional_min"]
    applied["EXCEPTIONAL_LENGTH"] = core.EXCEPTIONAL_LENGTH
    return applied


def load_pairing_rules_into_core(core, path):
    """Replace the hard-coded MANDATORY_PAIRING dict with the CSV rule table."""
    table = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            table.setdefault(r["activity"], []).append((
                r["compelled_dept"], r["companion_activity"],
                float(r["duration_mean_min"]), float(r["duration_sd_min"]),
                bool(int(r["must_follow_parent"])),
            ))
    core.MANDATORY_PAIRING = table
    return table


def load_sections(core, path):
    out = []
    with open(path) as f:
        for r in csv.DictReader(f):
            out.append(core.Section(
                id=r["section_id"], line=r["line"],
                is_single=bool(int(r["is_single"])),
                headway_min=int(r["headway_min"]),
                degraded_factor=float(r["degraded_factor"]) or 1.0))
    return out


def load_trains(core, movements_path):
    """One core.Train per section traversal, which is what the queue model wants."""
    out = []
    with open(movements_path) as f:
        for i, r in enumerate(csv.DictReader(f)):
            for line in (r["direction"], "SINGLE"):
                sid = f"{r['from_code']}-{r['to_code']}-{line}"
                out.append(core.Train(
                    id=f"{r['train_number']}#{i}", section_id=sid,
                    sched_min=int(float(r["enter_min"])),
                    klass=r["train_class"] if r["train_class"] in core.TRAIN_WEIGHT
                    else "UNKNOWN",
                    day_mask=127))
    return out


def load_jobs(core, path, section_ids):
    out, skipped = [], 0
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["section_id"] not in section_ids:
                skipped += 1
                continue
            out.append(core.Job(
                id=r["job_id"], dept=r["dept"], activity=r["activity"],
                section_id=r["section_id"],
                km_from=float(r["km_from"]), km_to=float(r["km_to"]),
                needs_T=bool(int(r["needs_T"])), needs_P=bool(int(r["needs_P"])),
                needs_D=bool(int(r["needs_D"])),
                needs_train_movements=bool(int(r["needs_train_movements"])),
                needs_live_ohe=bool(int(r["needs_live_ohe"])),
                dur_mean=float(r["duration_mean_min"]),
                dur_sd=float(r["duration_sd_min"]),
                resources=tuple(x for x in (r["resources"] or "").split("|") if x),
                due_day=int(r["due_day"]), criticality=float(r["criticality"])))
    return out, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../dataset")
    ap.add_argument("--config", default="../config")
    ap.add_argument("--core", required=True, help="directory containing core.py")
    ap.add_argument("--horizon", type=int, default=14)
    ap.add_argument("--max-jobs", type=int, default=0)
    args = ap.parse_args()

    sys.path.insert(0, os.path.abspath(args.core))
    import core                                     # noqa: E402

    print("=== config -> core.py constants ===")
    for k, v in load_config_into_core(core, args.config).items():
        print(f"  {k:24s} {v}")

    p = os.path.join(args.dataset, "processed")
    rules = load_pairing_rules_into_core(core, os.path.join(p, "pairing_rules.csv"))
    print(f"\n=== pairing rules from CSV: {sum(len(v) for v in rules.values())} "
          f"rows over {len(rules)} activities ===")
    for a, v in rules.items():
        for d, act, m, s, mf in v:
            print(f"  {a:22s} compels {d:4s} {act:22s} {m:5.0f}+-{s:<4.0f}"
                  f"{'  (must follow)' if mf else ''}")

    sections = load_sections(core, os.path.join(p, "sections.csv"))
    sids = {s.id for s in sections}
    trains = load_trains(core, os.path.join(p, "movements.csv"))
    trains = [t for t in trains if t.section_id in sids]
    jobs, skipped = load_jobs(core, os.path.join(p, "jobs.csv"), sids)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    print(f"\n=== dataset loaded ===")
    print(f"  {len(sections)} section-lines, {len(trains)} train movements, "
          f"{len(jobs)} jobs ({skipped} skipped)")

    jobs = core.expand_mandatory_pairings(jobs)
    print(f"  {len(jobs)} after mandatory-pairing expansion")

    print("\n=== running the optimiser on dataset input ===")
    import time
    t0 = time.perf_counter()
    bundles = core.enumerate_bundles(jobs, max_size=5)
    t_enum = time.perf_counter() - t0
    windows = core.generate_windows(sections, trains, args.horizon, keep_per_day=8)
    t0 = time.perf_counter()
    cols = core.build_columns(jobs, bundles, windows, theta=core.THETA,
                              mc_samples=1500)
    t_col = time.perf_counter() - t0
    res = core.solve(jobs, cols, sections, args.horizon, time_limit_s=60)

    idx = {j.id: j for j in jobs}
    cross = sum(1 for c in res["blocks"]
                if len({idx[j].dept for j in c.job_ids}) > 1)
    print(f"  bundles {len(bundles)} ({t_enum:.2f}s) | windows {len(windows)} | "
          f"columns {len(cols)} ({t_col:.1f}s)")
    print(f"  {res['status']} in {res['seconds']:.2f}s | {len(res['blocks'])} blocks | "
          f"{len(res['deferred'])} deferred | cross-department blocks "
          f"{cross}/{len(res['blocks'])} = {cross/max(1,len(res['blocks'])):.0%}")
    print("\n  first 8 blocks:")
    for c in res["blocks"][:8]:
        w = c.window
        depts = "".join(sorted({idx[j].dept[0] for j in c.job_ids}))
        print(f"    day {w.day:2d} {w.section_id:22s} "
              f"{w.start_min//60:02d}:{w.start_min%60:02d}+{w.length:3d} "
              f"R={c.reliability:.3f} traffic={w.traffic_cost:8.1f} "
              f"[{depts}] {'+'.join(c.job_ids[:5])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
