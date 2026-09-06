#!/usr/bin/env python3
"""Build the block-planning dataset.

    python generate_dataset.py --seed 42 --size medium
    python generate_dataset.py --seed 42 --source scaffold      # dev only

Running with the same seed and the same raw source hashes reproduces the same
dataset byte for byte. Changing the seed produces a different maintenance
scenario on the SAME real railway infrastructure, which is the property that
makes the benchmark useful.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict

import numpy as np
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dsgen import demand, network, provenance, report, scenarios, sources, validate  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "config")
OUT = os.path.join(ROOT, "dataset")

SIZES = {"small": 40, "medium": 180, "large": 400}


def load_yaml(name):
    with open(os.path.join(CONF, name)) as f:
        return yaml.safe_load(f)


def write_csv(path, rows, fieldnames=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not rows:
        open(path, "w").close()
        return
    fn = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fn, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--size", choices=list(SIZES), default="medium")
    ap.add_argument("--source", choices=["datameet", "scaffold"], default="datameet")
    ap.add_argument("--scenario", default="NORMAL_TRAFFIC")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    corridor_cfg = load_yaml("corridor.yaml")
    activities = load_yaml("activities.yaml")
    rules = load_yaml("rules.yaml")
    assumptions = load_yaml("assumptions.yaml")
    horizon = corridor_cfg["horizon"]["days"]
    rng = np.random.default_rng(args.seed)

    print(f"[1/8] raw source: {args.source}")
    if args.source == "datameet":
        raw = sources.fetch_datameet(os.path.join(args.out, "raw"))
    else:
        raw = sources.build_scaffold(seed=1)  # topology is seed-invariant, as with real data
        print("      SCAFFOLD MODE - placeholder geography, not for presentation")
        # the scaffold has no real station codes, so retarget the endpoints at
        # its own placeholder terminals and drop the via-anchor
        codes = [f["properties"]["code"] for f in raw.stations]
        corridor_cfg["study_area"]["endpoints"] = {
            "from_station_code": codes[0], "to_station_code": codes[-1]}
        corridor_cfg["study_area"]["via_station_codes"] = []
        corridor_cfg["study_area"]["name"] += " [SCAFFOLD]"

    print("[2/8] building corridor from real train routes")
    osm = None
    if corridor_cfg["track_configuration"]["source"] == "osm" and args.source == "datameet":
        pass  # bbox is only known after the corridor is built; see note below
    cor = network.build_corridor(raw, corridor_cfg, osm)
    network.assign_headways(cor, assumptions)
    print(f"      {len(cor.stations)} stations, "
          f"{len(cor.sections)} section-lines, "
          f"{len({(s.from_code, s.to_code) for s in cor.sections})} physical sections")
    if cor.published_distance_km:
        print(f"      distance scaled x{cor.scale_factor:.3f} to match the published "
              f"route distance of {cor.published_distance_km:.0f} km")
    else:
        print("      no published route distance matched; using unscaled great-circle "
              "distances (flagged in provenance)")

    print(f"[3/8] scenario {args.scenario}")
    sc = scenarios.SCENARIOS[args.scenario]

    print("[4/8] traffic layer")
    movements = list(cor.movements)
    movements += scenarios.generate_freight(cor, assumptions, rng,
                                            sc.get("freight_scale", 1.0))
    print(f"      {sum(1 for m in movements if not m['is_synthetic'])} real + "
          f"{sum(1 for m in movements if m['is_synthetic'])} synthetic freight movements")

    print("[5/8] maintenance demand")
    jobs = demand.generate_jobs(
        cor, activities, assumptions, horizon, args.seed,
        backlog_multiplier=sc.get("backlog", 1.0),
        demand_scale=sc.get("demand_scale", 1.0),
        uncertainty_scale=sc.get("uncertainty_scale", 1.0),
        target_jobs=SIZES[args.size])
    if sc.get("urgency_shift"):
        for j in jobs:
            j.due_day = max(-14, j.due_day + sc["urgency_shift"])
    print(f"      {len(jobs)} jobs "
          f"({', '.join(f'{d}={sum(1 for j in jobs if j.dept==d)}' for d in ('ENGG','SNT','TRD'))})")

    reqs = demand.generate_block_requests(jobs, rng, horizon)
    execu = demand.generate_execution(jobs, assumptions, args.seed)

    print("[6/8] writing tables")
    pdir = os.path.join(args.out, "processed")
    write_csv(os.path.join(pdir, "stations.csv"), [{
        "station_code": s.code, "station_name": s.name, "latitude": round(s.lat, 6),
        "longitude": round(s.lon, 6), "zone": s.zone, "state": s.state,
        "seq": s.seq, "is_junction": int(s.is_junction)} for s in cor.stations])
    write_csv(os.path.join(pdir, "sections.csv"), [{
        "section_id": s.section_id, "from_station_code": s.from_code,
        "to_station_code": s.to_code, "line": s.line, "length_km": s.length_km,
        "tracks": s.tracks, "electrified": int(s.electrified),
        "is_single": int(s.tracks < 2), "headway_min": s.headway_min,
        "degraded_factor": s.degraded_factor, "support_trains": s.support_trains,
        "track_source": s.track_source} for s in cor.sections])
    write_csv(os.path.join(pdir, "trains.csv"), list(cor.trains.values()))
    write_csv(os.path.join(pdir, "train_stops.csv"), cor.stops)
    write_csv(os.path.join(pdir, "movements.csv"), movements)
    write_csv(os.path.join(pdir, "jobs.csv"), demand.job_rows(jobs))
    write_csv(os.path.join(pdir, "block_requests.csv"), reqs)
    write_csv(os.path.join(pdir, "execution.csv"), execu)
    write_csv(os.path.join(pdir, "activities.csv"), [{
        "activity_id": a["id"], "dept": a["dept"], "label": a["label"],
        "asset": a["asset"], "needs_T": int(a["protection"]["T"]),
        "needs_P": int(a["protection"]["P"]), "needs_D": int(a["protection"]["D"]),
        "needs_train_movements": int(a.get("needs_train_movements", False)),
        "needs_live_ohe": int(a.get("needs_live_ohe", False)),
        "duration_mean_min": a["duration_min"]["mean"],
        "duration_sd_min": a["duration_min"]["sd"],
        "periodicity_days": a["periodicity_days"],
        "min_block_min": a["min_block_min"],
        "min_block_provenance": a.get("min_block_provenance", "E"),
        "resource_class": a["resource_class"],
        "criticality_base": a["criticality_base"],
        "protection_source": a.get("protection_source", ""),
    } for a in activities["activities"]])
    pr_rows = [{
        "activity": p["activity"], "compelled_dept": p["compelled_dept"],
        "companion_activity": p["companion_activity"],
        "duration_mean_min": p["duration_min"]["mean"],
        "duration_sd_min": p["duration_min"]["sd"],
        "must_follow_parent": int(p.get("must_follow_parent", False)),
        "precedes_parent": int(p.get("precedes_parent", False)),
        "source": p["source"], "confidence": p["confidence"],
    } for p in rules["mandatory_pairings"]]
    write_csv(os.path.join(pdir, "pairing_rules.csv"), pr_rows)
    write_csv(os.path.join(args.out, "scenarios", "scenarios.csv"), scenarios.rows())
    write_csv(os.path.join(pdir, "resources.csv"), [
        {"resource_class": k, "fleet_size": v, "provenance": "E"}
        for k, v in assumptions["resources"].items()])

    mdir = os.path.join(args.out, "metadata")
    os.makedirs(mdir, exist_ok=True)
    provenance.write(os.path.join(mdir, "DATA_PROVENANCE.csv"))

    meta = {
        "study_area": corridor_cfg["study_area"]["name"],
        "zone": corridor_cfg["study_area"]["zone"],
        "division": corridor_cfg["study_area"]["division"],
        "source_mode": raw.mode,
        "source_hashes": raw.hashes,
        "seed": args.seed, "size": args.size, "scenario": args.scenario,
        "horizon_days": horizon,
        "published_distance_km": cor.published_distance_km,
        "scale_factor": cor.scale_factor,
        "generator_version": "1.0",
        "NOTICE": ("Infrastructure, stations, coordinates and train schedules are real "
                   "public data. Maintenance jobs, block requests, freight paths and "
                   "execution realisations are SYNTHETIC. This is not Indian Railways "
                   "maintenance data and must never be described as such."),
    }
    with open(os.path.join(mdir, "manifest.json"), "w") as f:
        json.dump(meta, f, indent=2)

    ds = {
        "meta": meta,
        "stations": _read(pdir, "stations.csv", float_cols=("latitude", "longitude"),
                          int_cols=("seq", "is_junction")),
        "sections": _read(pdir, "sections.csv", float_cols=("length_km", "degraded_factor"),
                          int_cols=("tracks", "electrified", "is_single",
                                    "headway_min", "support_trains")),
        "jobs": _read(pdir, "jobs.csv",
                      float_cols=("km_from", "km_to", "duration_mean_min",
                                  "duration_sd_min", "duration_min_min",
                                  "duration_max_min", "criticality"),
                      int_cols=("needs_T", "needs_P", "needs_D",
                                "needs_train_movements", "needs_live_ohe",
                                "due_day", "min_block_min")),
        "train_stops": cor.stops,
        "movements": movements,
        "block_requests": reqs,
        "execution": execu,
        "pairing_rules": pr_rows,
        "scenarios": scenarios.rows(),
        "activities": activities,
        "assumptions": assumptions,
        "block_lengths": rules["block_envelope"]["single_line"]["options_min"],
    }

    print("[7/8] validating")
    results = validate.validate(ds)
    ok, summary = validate.summarise(results)
    with open(os.path.join(mdir, "validation.json"), "w") as f:
        json.dump(results, f, indent=2)
    for r in results:
        if not r["passed"]:
            print(f"      {r['level']:8s} {r['check']}: {r['detail']}")
    print(f"      {summary}")

    print("[8/8] report and figures")
    s = report.write(ds, mdir, os.path.join(args.out, "maps"))
    try:
        figs = report.figures(ds, os.path.join(args.out, "maps"))
        print(f"      {len(figs)} figures written")
    except Exception as e:                       # noqa: BLE001
        print(f"      figures skipped: {e}")

    print(f"\nDone. source_mode={raw.mode} seed={args.seed} size={args.size} "
          f"jobs={len(jobs)} sections={len(cor.sections)}")
    return 0 if ok else 1


def _read(d, name, float_cols=(), int_cols=()):
    with open(os.path.join(d, name)) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in float_cols:
            if c in r and r[c] != "":
                r[c] = float(r[c])
        for c in int_cols:
            if c in r and r[c] != "":
                r[c] = int(float(r[c]))
    return rows


if __name__ == "__main__":
    sys.exit(main())
