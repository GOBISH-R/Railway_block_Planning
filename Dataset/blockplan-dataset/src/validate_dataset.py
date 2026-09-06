#!/usr/bin/env python3
"""Validate a generated dataset.

    python validate_dataset.py --dataset ../dataset
    python validate_dataset.py --dataset ../dataset --allow-scaffold

Exits non-zero on any CRITICAL failure. A scaffold build fails by design: the
placeholder geography must never be presented as real, so certifying it
requires an explicit --allow-scaffold.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dsgen import validate  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path, float_cols=(), int_cols=()):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path) as f:
        rows = list(csv.DictReader(f))
    # A missing numeric value is written by csv.DictWriter as an empty field and
    # read back as '' rather than None. Left as '', it passes an `is not None`
    # guard and then blows up in arithmetic. Normalise it to None here so a CSV
    # round-trip yields the same types the generator validates in memory.
    for r in rows:
        for c in float_cols:
            if c in r:
                r[c] = float(r[c]) if r[c] not in ("", None) else None
        for c in int_cols:
            if c in r:
                r[c] = int(float(r[c])) if r[c] not in ("", None) else None
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=os.path.join(ROOT, "dataset"))
    ap.add_argument("--config", default=os.path.join(ROOT, "config"))
    ap.add_argument("--allow-scaffold", action="store_true")
    args = ap.parse_args()

    p = os.path.join(args.dataset, "processed")
    with open(os.path.join(args.dataset, "metadata", "manifest.json")) as f:
        meta = json.load(f)
    with open(os.path.join(args.config, "activities.yaml")) as f:
        activities = yaml.safe_load(f)
    with open(os.path.join(args.config, "rules.yaml")) as f:
        rules = yaml.safe_load(f)
    with open(os.path.join(args.config, "assumptions.yaml")) as f:
        assumptions = yaml.safe_load(f)

    ds = {
        "meta": meta,
        "stations": read(os.path.join(p, "stations.csv"),
                         ("latitude", "longitude"), ("seq", "is_junction")),
        "sections": read(os.path.join(p, "sections.csv"),
                         ("length_km", "degraded_factor"),
                         ("tracks", "electrified", "is_single", "headway_min",
                          "support_trains")),
        "jobs": read(os.path.join(p, "jobs.csv"),
                     ("km_from", "km_to", "duration_mean_min", "duration_sd_min",
                      "duration_min_min", "duration_max_min", "criticality"),
                     ("needs_T", "needs_P", "needs_D", "needs_train_movements",
                      "needs_live_ohe", "due_day", "min_block_min")),
        "train_stops": read(os.path.join(p, "train_stops.csv"), (),
                            ("arrival_min", "departure_min", "day", "stop_seq")),
        "movements": read(os.path.join(p, "movements.csv"), (), ("enter_min",)),
        "block_requests": read(os.path.join(p, "block_requests.csv"), (),
                               ("preferred_date", "preferred_window_start_min",
                                "minimum_duration_min", "requested_duration_min",
                                "deadline_day")),
        "execution": read(os.path.join(p, "execution.csv"), ("actual_duration_min",)),
        "pairing_rules": read(os.path.join(p, "pairing_rules.csv")),
        "scenarios": read(os.path.join(args.dataset, "scenarios", "scenarios.csv")),
        "activities": activities,
        "assumptions": assumptions,
        "block_lengths": rules["block_envelope"]["single_line"]["options_min"],
    }
    for m in ds["movements"]:
        m["is_synthetic"] = str(m.get("is_synthetic", "")).lower() in ("true", "1")

    results = validate.validate(ds)
    width = max(len(r["check"]) for r in results)
    for r in results:
        mark = "PASS" if r["passed"] else ("FAIL" if r["level"] == "CRITICAL" else "WARN")
        print(f"  [{mark}] {r['check']:<{width}}  {r['detail']}")
    ok, summary = validate.summarise(results)
    print("\n" + summary)

    if not ok and args.allow_scaffold:
        crit = [r for r in results if r["level"] == "CRITICAL" and not r["passed"]]
        if all(r["check"] == "source_mode_is_real" for r in crit):
            print("scaffold build accepted under --allow-scaffold (DEVELOPMENT ONLY)")
            return 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
