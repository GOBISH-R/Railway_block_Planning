"""Does the reliability constraint actually change anything?

At low load it mostly does not: cheap windows are plentiful, the optimiser
prefers small bundles anyway, and the constraint never binds. It bites under
competition. This script measures where the crossover is, which is the single
most important thing to know before designing the evaluation.
"""
import numpy as np

from core import (THETA, Job, build_columns, enumerate_bundles, evaluate,
                  expand_mandatory_pairings, generate_windows, solve)
from dense import BASE_JOBS, HORIZON_DAYS, SECTIONS, build_timetable


def make_backlog(n, seed=11):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        src = BASE_JOBS[i % 10]
        off = float(rng.uniform(0, 40))          # tight: forces competition
        out.append(Job(f"K{i:03d}", src.dept, src.activity,
                       ["S1", "S2U", "S2D"][i % 3],
                       round(off, 1), round(off + (src.km_to - src.km_from), 1),
                       src.needs_T, src.needs_P, src.needs_D,
                       dur_mean=src.dur_mean, dur_sd=src.dur_sd,
                       resources=(f"{src.resources[0]}_{i%3}",) if src.resources else (),
                       due_day=int(rng.integers(1, 4)),   # tight deadlines
                       criticality=src.criticality))
    return expand_mandatory_pairings(out)


def main():
    trains = build_timetable()
    windows = generate_windows(SECTIONS, trains, HORIZON_DAYS, keep_per_day=10)
    print(f"{'load':>5s} {'method':>14s} {'blocks':>7s} {'done':>5s} "
          f"{'traffic/job':>12s} {'E[overrun]':>11s} {'min R':>7s} "
          f"{'mean R':>7s} {'x-dept':>7s}")
    for n in (20, 40, 80, 120):
        jobs = make_backlog(n)
        bundles = enumerate_bundles(jobs, max_size=5)
        c_on = build_columns(jobs, bundles, windows, theta=THETA, mc_samples=2000)
        c_off = build_columns(jobs, bundles, windows,
                              reliability_required=False, mc_samples=2000)
        for label, cols in (("no reliability", c_off), ("OURS", c_on)):
            r = solve(jobs, cols, SECTIONS, HORIZON_DAYS, time_limit_s=45)
            e = evaluate(label, r["blocks"], jobs)
            print(f"{n:5d} {label:>14s} {e['blocks']:7d} {e['jobs_done']:5d} "
                  f"{e['traffic_per_job']:12.1f} {e['exp_overrun_cost']:11.1f} "
                  f"{e['min_reliability']:7.3f} {e['mean_reliability']:7.3f} "
                  f"{e['cross_dept_share']:7.2f}")
        print()


if __name__ == "__main__":
    main()
