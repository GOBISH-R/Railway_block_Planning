"""
BlockPlan demo — the worked example from the technical blueprint.

12 maintenance jobs (plus rule-generated companions), 18 trains, 3 section-lines,
14-day horizon. All instance data is SYNTHETIC. It is shaped to be plausible;
it is not Indian Railways data and must never be presented as such.
"""
from __future__ import annotations

import json
import sys

import numpy as np

import os

import core as core_mod
from core import (
    ALLOWED_BLOCK_LENGTHS, DEPTS, THETA, Column, Job, Section, Train,
    baseline_department_wise, baseline_fixed_calendar, baseline_greedy_earliest,
    build_columns, enumerate_bundles, evaluate, expand_mandatory_pairings,
    explain_refusal, generate_windows, reliability_closed_form, reliability_mc,
    solve, traffic_cost,
)

HORIZON_DAYS = 14

# ---------------------------------------------------------------- sections
SECTIONS = [
    Section("S1", "SINGLE", True, headway_min=15, degraded_factor=1.0),
    Section("S2U", "UP", False, headway_min=8, degraded_factor=2.5),
    Section("S2D", "DN", False, headway_min=8, degraded_factor=2.5),
]

# ---------------------------------------------------------------- timetable
# SYNTHETIC. 18 trains. Times are minutes from midnight, entry to the section.
def _t(i, sec, hhmm, klass):
    h, m = divmod(hhmm, 100)
    return Train(i, sec, h * 60 + m, klass, 127)

TRAINS = [
    _t("12621", "S1", 610, "EXPRESS"),
    _t("56312", "S1", 625, "FREIGHT"),
    _t("22671", "S1", 650, "PASSENGER"),
    _t("12627", "S1", 715, "EXPRESS"),
    _t("41023", "S1", 740, "FREIGHT"),
    _t("16302", "S1", 805, "EXPRESS"),
    _t("66301", "S1", 820, "MEMU"),
    _t("12695", "S1", 1150, "EXPRESS"),
    _t("57415", "S1", 1420, "PASSENGER"),
    _t("59001", "S1", 205, "FREIGHT"),
    _t("20643", "S2U", 545, "VANDE_BHARAT"),
    _t("12841", "S2U", 700, "EXPRESS"),
    _t("66512", "S2U", 745, "MEMU"),
    _t("58011", "S2U", 1030, "PASSENGER"),
    _t("40221", "S2U", 1330, "FREIGHT"),
    _t("12842", "S2D", 640, "EXPRESS"),
    _t("66513", "S2D", 810, "MEMU"),
    _t("40222", "S2D", 1400, "FREIGHT"),
]

# ---------------------------------------------------------------- jobs
# SYNTHETIC instance data. Durations are DECLARED estimates, not measurements.
BASE_JOBS = [
    Job("J01", "ENGG", "THROUGH_TAMPING", "S1", 10.0, 14.0,
        True, False, False, dur_mean=65, dur_sd=12,
        resources=("TAMPER_1",), due_day=12, criticality=1.4),
    Job("J02", "SNT", "POINT_MACHINE_OVERHAUL", "S1", 12.4, 12.6,
        True, False, True, dur_mean=45, dur_sd=10,
        resources=("SNT_GANG_A",), due_day=9, criticality=1.8),
    Job("J03", "ENGG", "DEEP_SCREENING", "S1", 15.0, 16.0,
        True, False, False, dur_mean=150, dur_sd=30,
        resources=("BCM_1",), due_day=20, criticality=1.0),
    Job("J04", "TRD", "INSULATOR_REPLACEMENT", "S1", 11.0, 11.2,
        True, True, False, dur_mean=40, dur_sd=9,
        resources=("TOWER_WAGON_1",), due_day=15, criticality=1.3),
    Job("J05", "SNT", "TRACK_CIRCUIT_CABLE", "S1", 13.0, 13.4,
        True, False, True, dur_mean=35, dur_sd=8,
        resources=("SNT_GANG_B",), due_day=18, criticality=1.1),
    Job("J06", "ENGG", "TURNOUT_TAMPING", "S2U", 3.0, 3.4,
        True, False, False, dur_mean=55, dur_sd=14,
        resources=("TAMPER_1",), due_day=7, criticality=1.6),
    Job("J07", "TRD", "OHE_DROPPER", "S2U", 4.0, 4.2,
        True, True, False, dur_mean=30, dur_sd=7,
        resources=("TOWER_WAGON_1",), due_day=14, criticality=1.2),
    Job("J08", "SNT", "SIGNAL_WIRING_ALTERATION", "S2D", 5.0, 5.2,
        True, False, True, dur_mean=50, dur_sd=11,
        resources=("SNT_GANG_A",), due_day=11, criticality=1.5),
    Job("J09", "ENGG", "RAIL_RENEWAL", "S2D", 6.0, 6.3,
        True, False, False, dur_mean=80, dur_sd=18,
        resources=("PQRS_1",), due_day=16, criticality=1.7),
    Job("J10", "TRD", "OHE_PATROL_REPAIR", "S2D", 7.0, 7.2,
        True, True, False, dur_mean=35, dur_sd=8,
        resources=("TOWER_WAGON_2",), due_day=13, criticality=1.0),
    # --- the two Class D cases: work that needs the negation of a block ---
    Job("J11", "SNT", "TRACK_CIRCUIT_SHUNT_CHECK", "S1", 13.0, 13.2,
        False, False, False, needs_train_movements=True,
        dur_mean=25, dur_sd=6, due_day=10, criticality=0.9),
    Job("J12", "TRD", "OHE_MEASUREMENT_UNDER_LOAD", "S2U", 4.0, 4.4,
        False, False, False, needs_live_ohe=True,
        dur_mean=30, dur_sd=7, due_day=17, criticality=0.8),
]


def banner(s):
    print("\n" + "=" * 74)
    print(s)
    print("=" * 74)


def main():
    # ONE source of truth for the mandatory-pairing rules: the CSV.
    core_mod.load_pairing_rules(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "pairing_rules.csv"))
    jobs = expand_mandatory_pairings([Job(**{**j.__dict__}) for j in BASE_JOBS])
    idx = {j.id: j for j in jobs}

    banner("STEP 1-2  jobs after mandatory-pairing expansion")
    print(f"{len(BASE_JOBS)} declared jobs -> {len(jobs)} after rule expansion "
          f"({len(jobs) - len(BASE_JOBS)} rule-generated companions)")
    for j in jobs:
        if j.is_companion:
            print(f"   + {j.id:8s} {j.dept:5s} {j.activity:24s} "
                  f"{j.dur_mean:5.0f}+-{j.dur_sd:<4.0f} compelled by {j.parent_id}"
                  + ("  (must follow parent)" if j.after else ""))

    banner("STEP 3  compatibility — a few worked verdicts")
    from core import pairwise_compatible
    checks = [("J01", "J04"), ("J01", "J02"), ("J02", "J05"), ("J01", "J03"),
              ("J01", "J11"), ("J07", "J12"), ("J01", "J01c0")]
    for a, b in checks:
        ok, why = pairwise_compatible(idx[a], idx[b])
        print(f"   {a:6s} + {b:6s} -> {'COMPATIBLE' if ok else 'INCOMPATIBLE':12s} "
              f"{'' if ok else '(' + why + ')'}")

    banner("STEP 4  bundle enumeration")
    t0 = __import__("time").perf_counter()
    bundles = enumerate_bundles(jobs, max_size=5)
    print(f"   {len(bundles)} valid bundles enumerated in "
          f"{__import__('time').perf_counter()-t0:.3f}s")
    sizes = {}
    for b in bundles:
        sizes[len(b)] = sizes.get(len(b), 0) + 1
    print("   by size:", dict(sorted(sizes.items())))
    multi = [b for b in bundles if len({idx[i].dept for i in b}) > 1]
    print(f"   cross-department bundles: {len(multi)}")

    banner("STEP 5  traffic cost — one worked window on S1 (single line)")
    sec1 = SECTIONS[0]
    for start, label in [(600, "10:00"), (120, "02:00"), (1080, "18:00")]:
        w, raw, aff = traffic_cost(sec1, start, 240, TRAINS)
        print(f"   S1  {label}-+240min : weighted {w:8.1f}  raw {raw:7.1f} "
              f"train-min  affected {aff}")

    banner("STEP 6  hand-back reliability — the frontier, in one table")
    print(f"   {'bundle':34s} {'depts':6s} {'sum mu':>7s} {'L=150':>8s} {'L=240':>8s}")
    demo_bundles = [
        ("J02",), ("J02", "J05"), ("J01", "J01c0", "J01c1"),
        ("J01", "J01c0", "J01c1", "J04"),
        ("J01", "J01c0", "J01c1", "J04", "J05"),
    ]
    for b in demo_bundles:
        bj = [idx[i] for i in b]
        nd = len({j.dept for j in bj})
        mu = sum(j.dur_mean for j in bj)
        r150 = reliability_mc(bj, 150)
        r240 = reliability_mc(bj, 240)
        print(f"   {'+'.join(b):34s} {nd:^6d} {mu:7.0f} {r150:8.3f} {r240:8.3f}")

    print("\n   closed-form check (normal approximation) on the 4-job bundle:")
    bj = [idx[i] for i in ("J01", "J01c0", "J01c1", "J04")]
    print(f"     MC={reliability_mc(bj,240):.3f}   "
          f"closed-form={reliability_closed_form(bj,240):.3f}")

    banner("STEP 7  window generation (the supply map)")
    t0 = __import__("time").perf_counter()
    windows = generate_windows(SECTIONS, TRAINS, HORIZON_DAYS)
    print(f"   {len(windows)} candidate windows kept in "
          f"{__import__('time').perf_counter()-t0:.2f}s")
    cheap = sorted(windows, key=lambda w: w.traffic_cost)[:5]
    for w in cheap:
        print(f"     {w.section_id:4s} day {w.day:2d} "
              f"{w.start_min//60:02d}:{w.start_min%60:02d} "
              f"+{w.length:3d}min  cost {w.traffic_cost:7.1f}")

    banner("STEP 8  column construction")
    t0 = __import__("time").perf_counter()
    cols = build_columns(jobs, bundles, windows, theta=THETA)
    print(f"   {len(cols)} admissible columns (bundle x window, reliability >= "
          f"{THETA}) in {__import__('time').perf_counter()-t0:.1f}s")
    cols_norel = build_columns(jobs, bundles, windows, reliability_required=False)
    print(f"   {len(cols_norel)} columns if the reliability filter is switched off "
          f"-> the filter removes {100*(1-len(cols)/max(1,len(cols_norel))):.0f}%")

    banner("STEP 9  optimisation (CP-SAT set packing)")
    res = solve(jobs, cols, SECTIONS, HORIZON_DAYS)
    print(f"   status {res['status']}  objective {res['objective']:.1f}  "
          f"in {res['seconds']:.2f}s over {res['n_columns']} columns")
    print(f"\n   {'day':>4s} {'sec':5s} {'window':13s} {'len':>4s} {'R':>6s} "
          f"{'traffic':>8s}  jobs")
    for c in res["blocks"]:
        w = c.window
        depts = sorted({idx[j].dept for j in c.job_ids})
        print(f"   {w.day:4d} {w.section_id:5s} "
              f"{w.start_min//60:02d}:{w.start_min%60:02d}-"
              f"{w.end_min//60:02d}:{w.end_min%60:02d}  {w.length:4d} "
              f"{c.reliability:6.3f} {w.traffic_cost:8.1f}  "
              f"{'+'.join(c.job_ids)}  [{','.join(depts)}]")
    print(f"\n   deferred: {res['deferred']}")

    banner("STEP 10  refusal explanation")
    for jid in res["deferred"]:
        e = explain_refusal(idx[jid], jobs, cols, windows)
        print(f"   {e['job']}: {e['candidate_columns']} admissible columns")
        for lv in e["levers"]:
            print(f"      - {lv['lever']:22s} {lv.get('reliability','   -')}  "
                  f"{lv['verdict']}")

    banner("STEP 11  baselines on the identical instance")
    rows = []
    b0, _ = baseline_department_wise(jobs, bundles, windows, SECTIONS,
                                 HORIZON_DAYS, reliability_required=False)
    b1, _ = baseline_department_wise(jobs, bundles, windows, SECTIONS,
                                     HORIZON_DAYS, reliability_required=True)
    rows.append(evaluate("B0 department-wise, no reliability", b0, jobs))
    rows.append(evaluate("B1 department-wise + reliability", b1, jobs))
    b2, _ = baseline_fixed_calendar(jobs, windows, SECTIONS, HORIZON_DAYS)
    rows.append(evaluate("B2 fixed calendar", b2, jobs))
    b3, _ = baseline_greedy_earliest(jobs, bundles, windows, HORIZON_DAYS)
    rows.append(evaluate("B3 greedy earliest", b3, jobs))
    res_ab = solve(jobs, cols_norel, SECTIONS, HORIZON_DAYS)
    rows.append(evaluate("B4 bundling, no reliability", res_ab["blocks"], jobs))
    rows.append(evaluate("OURS bundling + reliability", res["blocks"], jobs))

    hdr = ["method", "blocks", "jobs_done", "jobs_deferred", "traffic_cost",
           "exp_overrun_cost", "cross_dept_share", "mean_reliability",
           "min_reliability", "block_utilisation"]
    print("   " + " ".join(f"{h[:13]:>14s}" for h in hdr))
    for r in rows:
        print("   " + " ".join(f"{str(r[h])[:13]:>14s}" for h in hdr))

    banner("STEP 12  the headline: bundling-reliability frontier")
    print(f"   {'jobs in block':>14s} {'depts':>6s} {'traffic/job':>12s} "
          f"{'reliability':>12s} {'E[overrun]':>11s}")
    frontier = []
    base = ["J01", "J01c0", "J01c1"]
    adds = ["J04", "J05", "J02"]
    cur = list(base)
    w = min((w for w in windows if w.section_id == "S1" and w.length == 240),
            key=lambda w: w.traffic_cost)
    for k in range(len(adds) + 1):
        bj = [idx[i] for i in cur]
        r = reliability_mc(bj, 240)
        from core import expected_overrun_cost
        ov = expected_overrun_cost(bj, 240)
        nreal = len([j for j in bj if not j.is_companion])
        print(f"   {nreal:>14d} {len({j.dept for j in bj}):>6d} "
              f"{w.traffic_cost/max(1,nreal):>12.1f} {r:>12.3f} {ov:>11.1f}")
        frontier.append((nreal, r, w.traffic_cost / max(1, nreal), ov))
        if k < len(adds):
            cur.append(adds[k])

    print("\n   Reading: traffic cost per job retired falls as the bundle grows;")
    print("   reliability falls with it. The optimiser buys the first and pays")
    print("   the second, and theta is where we stop buying.")


if __name__ == "__main__":
    main()
