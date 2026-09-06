"""
Dense instance — the one the evaluation should actually run on.

The 18-train illustration in the blueprint is readable but degenerate: at that
density the timetable leaves so much free capacity that every method finds a
zero-cost window and all four baselines tie. Realistic single-line sections on
Indian Railways carry tens of trains a day. This module builds a plausible
daily pattern so that block windows genuinely compete.

Everything here is SYNTHETIC and generated from a declared pattern. It is not
Indian Railways data.
"""
from __future__ import annotations

import time

import numpy as np

import os

import core as core_mod
from core import (
    THETA, Job, Section, Train, baseline_department_wise,
    baseline_fixed_calendar, baseline_greedy_earliest, build_columns,
    enumerate_bundles, evaluate, expand_mandatory_pairings, explain_refusal,
    expected_overrun_cost, generate_windows, reliability_mc, solve,
    traffic_cost,
)

SECTIONS = [
    Section("S1", "SINGLE", True, headway_min=15, degraded_factor=1.0),
    Section("S2U", "UP", False, headway_min=8, degraded_factor=2.5),
    Section("S2D", "DN", False, headway_min=8, degraded_factor=2.5),
]

# DECL: a plausible daily traffic pattern. Peaks morning and evening, a midday
#       trough, freight concentrated at night. These shapes are assumptions.
PATTERN = {
    "S1": [  # (start_hhmm, end_hhmm, count, class)
        (0, 5, 6, "FREIGHT"),
        (5, 9, 9, "EXPRESS"),
        (6, 10, 4, "PASSENGER"),
        (9, 13, 3, "FREIGHT"),
        (10, 14, 2, "EXPRESS"),
        (14, 18, 4, "EXPRESS"),
        (16, 21, 4, "PASSENGER"),
        (18, 24, 6, "EXPRESS"),
        (21, 24, 4, "FREIGHT"),
    ],
    "S2U": [
        (0, 5, 5, "FREIGHT"),
        (5, 10, 8, "EXPRESS"),
        (6, 11, 6, "MEMU"),
        (11, 16, 4, "PASSENGER"),
        (16, 22, 8, "EXPRESS"),
        (17, 22, 5, "MEMU"),
        (22, 24, 3, "FREIGHT"),
    ],
    "S2D": [
        (0, 5, 5, "FREIGHT"),
        (5, 10, 7, "EXPRESS"),
        (6, 11, 6, "MEMU"),
        (11, 16, 3, "PASSENGER"),
        (16, 22, 8, "EXPRESS"),
        (17, 22, 5, "MEMU"),
        (22, 24, 3, "FREIGHT"),
    ],
}


def build_timetable(seed: int = 7) -> list[Train]:
    rng = np.random.default_rng(seed)
    trains: list[Train] = []
    n = 0
    for sec, blocks in PATTERN.items():
        for (h0, h1, count, klass) in blocks:
            times = np.sort(rng.uniform(h0 * 60, h1 * 60, count).astype(int))
            for t in times:
                n += 1
                trains.append(Train(f"T{n:04d}", sec, int(t), klass, 127))
    return trains


# ONE source of truth for the mandatory-pairing rules: the CSV beside this file.
# core.MANDATORY_PAIRING starts empty and expand_mandatory_pairings refuses to
# run without it, so a forgotten load fails loudly instead of silently producing
# single-department bundles.
core_mod.load_pairing_rules(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "pairing_rules.csv"))

HORIZON_DAYS = 7

BASE_JOBS = [
    Job("J01", "ENGG", "THROUGH_TAMPING", "S1", 10.0, 14.0, True, False, False,
        dur_mean=65, dur_sd=12, resources=("TAMPER_1",), due_day=5, criticality=1.4),
    Job("J02", "SNT", "POINT_MACHINE_OVERHAUL", "S1", 12.4, 12.6, True, False, True,
        dur_mean=45, dur_sd=10, resources=("SNT_GANG_A",), due_day=3, criticality=1.8),
    Job("J03", "ENGG", "DEEP_SCREENING", "S1", 15.0, 16.0, True, False, False,
        dur_mean=150, dur_sd=30, resources=("BCM_1",), due_day=6, criticality=1.0),
    Job("J04", "TRD", "INSULATOR_REPLACEMENT", "S1", 11.0, 11.2, True, True, False,
        dur_mean=40, dur_sd=9, resources=("TOWER_WAGON_1",), due_day=6, criticality=1.3),
    Job("J05", "SNT", "TRACK_CIRCUIT_CABLE", "S1", 13.0, 13.4, True, False, True,
        dur_mean=35, dur_sd=8, resources=("SNT_GANG_B",), due_day=6, criticality=1.1),
    Job("J06", "ENGG", "TURNOUT_TAMPING", "S2U", 3.0, 3.4, True, False, False,
        dur_mean=55, dur_sd=14, resources=("TAMPER_1",), due_day=3, criticality=1.6),
    Job("J07", "TRD", "OHE_DROPPER", "S2U", 4.0, 4.2, True, True, False,
        dur_mean=30, dur_sd=7, resources=("TOWER_WAGON_1",), due_day=6, criticality=1.2),
    Job("J08", "SNT", "SIGNAL_WIRING_ALTERATION", "S2D", 5.0, 5.2, True, False, True,
        dur_mean=50, dur_sd=11, resources=("SNT_GANG_A",), due_day=4, criticality=1.5),
    Job("J09", "ENGG", "RAIL_RENEWAL", "S2D", 6.0, 6.3, True, False, False,
        dur_mean=80, dur_sd=18, resources=("PQRS_1",), due_day=6, criticality=1.7),
    Job("J10", "TRD", "OHE_PATROL_REPAIR", "S2D", 7.0, 7.2, True, True, False,
        dur_mean=35, dur_sd=8, resources=("TOWER_WAGON_2",), due_day=5, criticality=1.0),
    Job("J11", "SNT", "TRACK_CIRCUIT_SHUNT_CHECK", "S1", 13.0, 13.2, False, False,
        False, needs_train_movements=True, dur_mean=25, dur_sd=6, due_day=4,
        criticality=0.9),
    Job("J12", "TRD", "OHE_MEASUREMENT_UNDER_LOAD", "S2U", 4.0, 4.4, False, False,
        False, needs_live_ohe=True, dur_mean=30, dur_sd=7, due_day=6,
        criticality=0.8),
    # extra load so windows genuinely compete
    Job("J13", "ENGG", "THROUGH_TAMPING", "S2D", 8.0, 11.0, True, False, False,
        dur_mean=70, dur_sd=15, resources=("TAMPER_2",), due_day=4, criticality=1.5),
    Job("J14", "SNT", "POINT_MACHINE_OVERHAUL", "S2U", 3.6, 3.8, True, False, True,
        dur_mean=45, dur_sd=10, resources=("SNT_GANG_B",), due_day=5, criticality=1.6),
    Job("J15", "TRD", "INSULATOR_REPLACEMENT", "S2D", 9.5, 9.7, True, True, False,
        dur_mean=40, dur_sd=9, resources=("TOWER_WAGON_2",), due_day=3, criticality=1.4),
]


def banner(s):
    print("\n" + "=" * 78)
    print(s)
    print("=" * 78)


def run():
    trains = build_timetable()
    jobs = expand_mandatory_pairings([Job(**{**j.__dict__}) for j in BASE_JOBS])
    idx = {j.id: j for j in jobs}

    banner("INSTANCE")
    per_sec = {}
    for t in trains:
        per_sec[t.section_id] = per_sec.get(t.section_id, 0) + 1
    print(f"   {len(trains)} trains/day  {per_sec}")
    print(f"   {len(BASE_JOBS)} declared jobs -> {len(jobs)} after mandatory-pairing "
          f"expansion;  horizon {HORIZON_DAYS} days")

    banner("TRAFFIC COST OF THE SAME BLOCK AT DIFFERENT TIMES (S1, single line)")
    print(f"   {'start':>7s} {'len':>5s} {'weighted':>10s} {'raw':>8s} {'affected':>9s}")
    for start in (0, 120, 300, 600, 720, 840, 1020, 1260):
        for length in (150, 240):
            w, raw, aff = traffic_cost(SECTIONS[0], start, length, trains)
            print(f"   {start//60:02d}:{start%60:02d}   {length:5d} {w:10.1f} "
                  f"{raw:8.1f} {aff:9d}")

    banner("SUPPLY MAP")
    t0 = time.perf_counter()
    windows = generate_windows(SECTIONS, trains, HORIZON_DAYS, keep_per_day=10)
    print(f"   {len(windows)} windows kept in {time.perf_counter()-t0:.2f}s")
    costs = sorted(w.traffic_cost for w in windows)
    print(f"   traffic cost of kept windows: min {costs[0]:.0f}  "
          f"median {costs[len(costs)//2]:.0f}  max {costs[-1]:.0f}")
    nz = [c for c in costs if c > 0]
    print(f"   {len(nz)}/{len(costs)} kept windows have non-zero traffic cost")

    banner("BUNDLES AND COLUMNS")
    t0 = time.perf_counter()
    bundles = enumerate_bundles(jobs, max_size=5)
    te = time.perf_counter() - t0
    sizes = {}
    for b in bundles:
        sizes[len(b)] = sizes.get(len(b), 0) + 1
    multi = [b for b in bundles if len({idx[i].dept for i in b}) > 1]
    print(f"   {len(bundles)} bundles in {te:.3f}s   sizes {dict(sorted(sizes.items()))}"
          f"   cross-department {len(multi)}")
    t0 = time.perf_counter()
    cols = build_columns(jobs, bundles, windows, theta=THETA)
    cols_norel = build_columns(jobs, bundles, windows, reliability_required=False)
    print(f"   {len(cols)} admissible columns (R >= {THETA}) / {len(cols_norel)} "
          f"unfiltered  in {time.perf_counter()-t0:.1f}s  "
          f"-> reliability filter removes "
          f"{100*(1-len(cols)/max(1,len(cols_norel))):.0f}%")

    banner("OUR PLAN")
    res = solve(jobs, cols, SECTIONS, HORIZON_DAYS)
    print(f"   {res['status']}  objective {res['objective']:.1f}  "
          f"{res['seconds']:.2f}s over {res['n_columns']} columns")
    print(f"\n   {'day':>3s} {'sec':5s} {'window':12s} {'len':>4s} {'R':>6s} "
          f"{'traffic':>8s}  jobs")
    for c in res["blocks"]:
        w = c.window
        depts = sorted({idx[j].dept for j in c.job_ids})
        print(f"   {w.day:3d} {w.section_id:5s} "
              f"{w.start_min//60:02d}:{w.start_min%60:02d}-"
              f"{w.end_min//60:02d}:{w.end_min%60:02d} {w.length:4d} "
              f"{c.reliability:6.3f} {w.traffic_cost:8.1f}  "
              f"{'+'.join(c.job_ids):38s} [{','.join(d[0] for d in depts)}]")
    print(f"\n   deferred: {res['deferred'] or 'none'}")

    if res["deferred"]:
        banner("REFUSAL EXPLANATION")
        for jid in res["deferred"]:
            e = explain_refusal(idx[jid], jobs, cols, windows, SECTIONS,
                                HORIZON_DAYS, res["objective"])
            print(f"\n   {e['job']} ({idx[jid].activity}) -> {e['verdict']}"
                  f"   [{e['candidate_columns']} admissible columns]")
            for lv in e.get("levers", []):
                r = lv.get("reliability")
                print(f"      - {lv['lever']:28s} "
                      f"R={'   -  ' if r is None else f'{r:.3f}'}  {lv['verdict']}")
            if e["verdict"] == "OUTBID":
                w = e["would_go_in"]
                print(f"      - price of forcing it in: "
                      f"+{e['price_of_forcing']:.1f} objective units")
                if w:
                    print(f"      - it would go: day {w['day']} "
                          f"{w['start']//60:02d}:{w['start']%60:02d} +{w['length']}min"
                          f"  with {w['with'] or 'nothing'}  R={w['reliability']}"
                          f"  traffic={w['traffic_cost']}")
                print(f"      - and would displace: {e['displaced'] or 'nothing'}")

    banner("BASELINE COMPARISON, IDENTICAL INSTANCE")
    rows = []
    b0, _ = baseline_department_wise(jobs, bundles, windows, SECTIONS,
                                 HORIZON_DAYS, reliability_required=False)
    b1, _ = baseline_department_wise(jobs, bundles, windows, SECTIONS,
                                     HORIZON_DAYS, reliability_required=True)
    rows.append(evaluate("B0 dept-wise no-rel", b0, jobs))
    rows.append(evaluate("B1 dept-wise +rel", b1, jobs))
    b2, _ = baseline_fixed_calendar(jobs, windows, SECTIONS, HORIZON_DAYS)
    rows.append(evaluate("B2 fixed-cal", b2, jobs))
    b3, _ = baseline_greedy_earliest(jobs, bundles, windows, HORIZON_DAYS)
    rows.append(evaluate("B3 greedy", b3, jobs))
    res_ab = solve(jobs, cols_norel, SECTIONS, HORIZON_DAYS)
    rows.append(evaluate("B4 bundle-only", res_ab["blocks"], jobs))
    rows.append(evaluate("OURS", res["blocks"], jobs))
    hdr = [("method", 14), ("blocks", 7), ("jobs_done", 10), ("jobs_deferred", 14),
           ("traffic_cost", 13), ("traffic_per_job", 16), ("exp_overrun_cost", 17),
           ("cross_dept_share", 17), ("mean_reliability", 17),
           ("min_reliability", 16), ("block_utilisation", 18)]
    print("   " + "".join(f"{h:>{w}s}" for h, w in hdr))
    for r in rows:
        print("   " + "".join(f"{str(r[h])[:w-1]:>{w}s}" for h, w in hdr))

    banner("THE FRONTIER — same jobs, two block envelopes")
    w150 = sorted([w for w in windows if w.section_id == "S1"
                   and w.length == 150 and w.traffic_cost > 0],
                  key=lambda w: w.traffic_cost)[0]
    w240 = sorted([w for w in windows if w.section_id == "S1"
                   and w.length == 240 and w.traffic_cost > 0],
                  key=lambda w: w.traffic_cost)[0]
    print(f"   150-min window: traffic {w150.traffic_cost:.0f} | "
          f"240-min window: traffic {w240.traffic_cost:.0f} weighted train-min")
    print(f"\n   {'jobs':>5s} {'dept':>5s} {'sum mu':>7s} | "
          f"{'L=150: t/job':>13s} {'R':>7s} {'ok':>4s} | "
          f"{'L=240: t/job':>13s} {'R':>7s} {'ok':>4s}")
    cur = ["J01", "J01c0", "J01c1"]
    for add in [None, "J04", "J05", "J02"]:
        if add:
            cur.append(add)
        bj = [idx[i] for i in cur]
        nreal = len([j for j in bj if not j.is_companion])
        r150, r240 = reliability_mc(bj, 150), reliability_mc(bj, 240)
        print(f"   {nreal:>5d} {len({j.dept for j in bj}):>5d} "
              f"{sum(j.dur_mean for j in bj):>7.0f} | "
              f"{w150.traffic_cost/nreal:>13.1f} {r150:>7.3f} "
              f"{'yes' if r150 >= THETA else 'NO':>4s} | "
              f"{w240.traffic_cost/nreal:>13.1f} {r240:>7.3f} "
              f"{'yes' if r240 >= THETA else 'NO':>4s}")

    banner("PLAN STABILITY — re-solve after new defects arrive")
    rng = np.random.default_rng(3)
    churns = []
    for trial in range(5):
        extra = []
        for k in range(3):
            src = BASE_JOBS[int(rng.integers(0, 10))]
            extra.append(Job(f"N{trial}{k}", src.dept, src.activity, src.section_id,
                             float(rng.uniform(20, 30)), float(rng.uniform(30, 31)),
                             src.needs_T, src.needs_P, src.needs_D,
                             dur_mean=src.dur_mean, dur_sd=src.dur_sd,
                             resources=(), due_day=int(rng.integers(2, 6)),
                             criticality=1.9))
        jobs2 = expand_mandatory_pairings(
            [Job(**{**j.__dict__}) for j in BASE_JOBS] + extra)
        b2 = enumerate_bundles(jobs2, max_size=5)
        c2 = build_columns(jobs2, b2, windows, theta=THETA)
        r2 = solve(jobs2, c2, SECTIONS, HORIZON_DAYS)
        before = {(c.window.day, c.window.section_id, c.window.start_min,
                   c.job_ids) for c in res["blocks"]}
        after = {(c.window.day, c.window.section_id, c.window.start_min,
                  c.job_ids) for c in r2["blocks"]
                 if not any(j.startswith("N") for j in c.job_ids)}
        kept = len(before & after)
        churn = 1 - kept / max(1, len(before))
        churns.append(churn)
        print(f"   trial {trial}: 3 urgent jobs injected -> {kept}/{len(before)} "
              f"original blocks unchanged, churn {churn:.1%}")
    print(f"\n   mean churn over 5 injections: {np.mean(churns):.1%}  "
          f"(no stability penalty in the objective yet — this is the baseline "
          f"a churn penalty would improve on)")

    banner("SCALE TEST  (jobs spread over a 120 km division, 3 section-lines)")
    print(f"   {'jobs':>5s} {'expanded':>9s} {'bundles':>8s} {'t_enum':>8s} "
          f"{'columns':>9s} {'t_cols':>8s} {'t_solve':>8s} {'status':>9s} "
          f"{'blocks':>7s} {'defer':>6s}")
    for n_jobs in (30, 60, 120, 250, 500):
        big = []
        rng = np.random.default_rng(11)
        for i in range(n_jobs):
            src = BASE_JOBS[i % 10]
            off = float(rng.uniform(0, 120))
            big.append(Job(f"K{i:03d}", src.dept, src.activity,
                           ["S1", "S2U", "S2D"][i % 3],
                           round(off, 1), round(off + (src.km_to - src.km_from), 1),
                           src.needs_T, src.needs_P, src.needs_D,
                           dur_mean=src.dur_mean, dur_sd=src.dur_sd,
                           resources=(f"{src.resources[0]}_{i%6}",) if src.resources else (),
                           due_day=int(rng.integers(2, HORIZON_DAYS)),
                           criticality=src.criticality))
        big = expand_mandatory_pairings(big)
        t0 = time.perf_counter()
        bb = enumerate_bundles(big, max_size=5)
        t_enum = time.perf_counter() - t0
        t0 = time.perf_counter()
        cc = build_columns(big, bb, windows, theta=THETA, mc_samples=1500)
        t_col = time.perf_counter() - t0
        rr = solve(big, cc, SECTIONS, HORIZON_DAYS, time_limit_s=60)
        print(f"   {n_jobs:5d} {len(big):9d} {len(bb):8d} {t_enum:7.2f}s "
              f"{len(cc):9d} {t_col:7.2f}s {rr['seconds']:7.2f}s "
              f"{rr['status']:>9s} {len(rr['blocks']):7d} {len(rr['deferred']):6d}")


if __name__ == "__main__":
    run()
