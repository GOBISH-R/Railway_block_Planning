#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import csv
import importlib.util
import os
import sys


def load_core(core_dir):
    core_path = os.path.join(core_dir, "core.py")

    spec = importlib.util.spec_from_file_location(
        "blockplan_core",
        core_path,
    )

    core = importlib.util.module_from_spec(spec)
    sys.modules["blockplan_core"] = core
    spec.loader.exec_module(core)

    return core


def load_adapter(adapter_path):
    spec = importlib.util.spec_from_file_location(
        "blockplan_adapter",
        adapter_path,
    )

    adapter = importlib.util.module_from_spec(spec)
    sys.modules["blockplan_adapter"] = adapter
    spec.loader.exec_module(adapter)

    return adapter


def reset_rng(core, state):
    core.RNG.bit_generator.state = copy.deepcopy(state)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dataset",
        default="..",
    )

    parser.add_argument(
        "--core",
        default="../blockplan",
    )

    parser.add_argument(
        "--horizon",
        type=int,
        default=14,
    )

    args = parser.parse_args()

    # ---------------------------------------------------------
    # Project paths
    # ---------------------------------------------------------

    project_dir = os.path.abspath(args.dataset)
    core_dir = os.path.abspath(args.core)

    src_dir = os.path.dirname(
        os.path.abspath(__file__)
    )

    # ---------------------------------------------------------
    # Load modules
    # ---------------------------------------------------------

    adapter = load_adapter(
        os.path.join(
            src_dir,
            "blockplan_adapter.py",
        )
    )

    core = load_core(
        core_dir
    )

    # ---------------------------------------------------------
    # Resolve actual dataset structure.
    #
    # Expected structure:
    #
    # blockplan-dataset/
    # ├── config/
    # └── dataset/
    #     ├── processed/
    #     └── scenarios/
    #
    # ---------------------------------------------------------

    config_dir = os.path.join(
        project_dir,
        "config",
    )

    data_dir = os.path.join(
        project_dir,
        "dataset",
    )

    # Fallback if --dataset itself points directly to dataset/
    if not os.path.isdir(data_dir):
        data_dir = project_dir

    processed = os.path.join(
        data_dir,
        "processed",
    )

    scenarios_dir = os.path.join(
        data_dir,
        "scenarios",
    )

    # ---------------------------------------------------------
    # Validate paths before doing any computation.
    # ---------------------------------------------------------

    required_paths = [
        os.path.join(
            config_dir,
            "assumptions.yaml",
        ),
        os.path.join(
            processed,
            "sections.csv",
        ),
        os.path.join(
            processed,
            "movements.csv",
        ),
        os.path.join(
            processed,
            "jobs.csv",
        ),
        os.path.join(
            processed,
            "pairing_rules.csv",
        ),
        os.path.join(
            scenarios_dir,
            "scenarios.csv",
        ),
    ]

    missing = [
        path
        for path in required_paths
        if not os.path.exists(path)
    ]

    if missing:
        print("ERROR: Required dataset files are missing:")

        for path in missing:
            print(
                f"  {path}"
            )

        print()
        print(
            "Check the --dataset path and dataset folder structure."
        )

        return 1

    # ---------------------------------------------------------
    # Load configuration and pairing rules.
    # ---------------------------------------------------------

    adapter.load_config_into_core(
        core,
        config_dir,
    )

    adapter.load_pairing_rules_into_core(
        core,
        os.path.join(
            processed,
            "pairing_rules.csv",
        ),
    )

    print(
        "=== REAL-DATA METHOD COMPARISON ==="
    )

    # ---------------------------------------------------------
    # Load real-derived dataset.
    # ---------------------------------------------------------

    sections = adapter.load_sections(
        core,
        os.path.join(
            processed,
            "sections.csv",
        ),
    )

    trains = adapter.load_trains(
        core,
        os.path.join(
            processed,
            "movements.csv",
        ),
    )

    section_ids = {
        s.id
        for s in sections
    }

    jobs, skipped = adapter.load_jobs(
        core,
        os.path.join(
            processed,
            "jobs.csv",
        ),
        section_ids,
    )

    print(
        f"sections={len(sections)} "
        f"trains={len(trains)} "
        f"jobs={len(jobs)} "
        f"skipped={skipped}"
    )

    # ---------------------------------------------------------
    # Protect against unknown train classes.
    # ---------------------------------------------------------

    original_weights = copy.deepcopy(
        core.TRAIN_WEIGHT
    )

    if "UNKNOWN" not in core.TRAIN_WEIGHT:
        core.TRAIN_WEIGHT["UNKNOWN"] = 1.0

    # ---------------------------------------------------------
    # Load NORMAL_TRAFFIC scenario.
    # ---------------------------------------------------------

    scenario_path = os.path.join(
        scenarios_dir,
        "scenarios.csv",
    )

    scenarios = adapter.load_scenarios(
        scenario_path
    )

    normal = next(
        s
        for s in scenarios
        if s["scenario"] == "NORMAL_TRAFFIC"
    )

    jobs, _ = adapter.load_scenario_jobs(
        core,
        data_dir,
        normal,
        section_ids,
    )

    trains = adapter.add_peak_passenger_traffic(
        core,
        list(trains),
        sections,
        normal,
    )

    # ---------------------------------------------------------
    # Build the common instance ONCE.
    # ---------------------------------------------------------

    jobs = core.expand_mandatory_pairings(
        jobs
    )

    windows = core.generate_windows(
        sections,
        trains,
        args.horizon,
        keep_per_day=8,
    )

    bundles = core.enumerate_bundles(
        jobs,
        max_size=5,
    )

    print(
        f"paired_jobs={len(jobs)} "
        f"windows={len(windows)} "
        f"bundles={len(bundles)}"
    )

    # ---------------------------------------------------------
    # Save RNG state BEFORE any reliability Monte Carlo calls.
    #
    # Every method starts from exactly the same random state.
    # ---------------------------------------------------------

    initial_rng_state = copy.deepcopy(
        core.RNG.bit_generator.state
    )

    results = []

    # =========================================================
    # B0 — Department-wise, NO reliability filter.
    #
    # This is the baseline that stands for current practice. Nobody in a
    # division computes a hand-back probability today, so a "current practice"
    # baseline may not quietly apply our chance constraint. The previous B1 did
    # exactly that, because build_columns defaults reliability_required to True,
    # which is why B1's min reliability came out at exactly theta.
    # =========================================================

    reset_rng(
        core,
        initial_rng_state,
    )

    b0, _ = core.baseline_department_wise(
        jobs,
        bundles,
        windows,
        sections,
        args.horizon,
        reliability_required=False,
    )

    results.append(
        core.evaluate(
            "B0 Dept-wise, no reliability",
            b0,
            jobs,
        )
    )

    # =========================================================
    # B1 — Department-wise WITH the reliability filter.
    #
    # Our method with cross-department bundling switched off.
    #   B0 -> B1   effect of the reliability filter alone
    #   B1 -> OURS effect of integrated cross-department bundling
    # =========================================================

    reset_rng(
        core,
        initial_rng_state,
    )

    b1, _ = core.baseline_department_wise(
        jobs,
        bundles,
        windows,
        sections,
        args.horizon,
        reliability_required=True,
    )

    results.append(
        core.evaluate(
            "B1 Dept-wise + reliability",
            b1,
            jobs,
        )
    )

    # =========================================================
    # B2 — Fixed calendar
    # =========================================================

    reset_rng(
        core,
        initial_rng_state,
    )

    b2, _ = core.baseline_fixed_calendar(
        jobs,
        windows,
        sections,
        args.horizon,
    )

    results.append(
        core.evaluate(
            "B2 Fixed-calendar",
            b2,
            jobs,
        )
    )

    # =========================================================
    # B3 — Greedy earliest
    # =========================================================

    reset_rng(
        core,
        initial_rng_state,
    )

    b3, _ = core.baseline_greedy_earliest(
        jobs,
        bundles,
        windows,
        args.horizon,
    )

    results.append(
        core.evaluate(
            "B3 Greedy-earliest",
            b3,
            jobs,
        )
    )

    # =========================================================
    # B4 — Bundle-only
    # =========================================================

    reset_rng(
        core,
        initial_rng_state,
    )

    columns_b4 = core.build_columns(
        jobs,
        bundles,
        windows,
        theta=core.THETA,
        reliability_required=False,
        mc_samples=1500,
    )

    b4 = core.solve(
        jobs,
        columns_b4,
        sections,
        args.horizon,
        time_limit_s=60,
    )

    results.append(
        core.evaluate(
            "B4 Bundle-only",
            b4["blocks"],
            jobs,
        )
    )

    # =========================================================
    # OURS — Reliability-aware
    # =========================================================

    reset_rng(
        core,
        initial_rng_state,
    )

    columns_ours = core.build_columns(
        jobs,
        bundles,
        windows,
        theta=core.THETA,
        reliability_required=True,
        mc_samples=1500,
    )

    ours = core.solve(
        jobs,
        columns_ours,
        sections,
        args.horizon,
        time_limit_s=60,
    )

    results.append(
        core.evaluate(
            "OURS",
            ours["blocks"],
            jobs,
        )
    )

    # ---------------------------------------------------------
    # Restore state after experiment.
    # ---------------------------------------------------------

    reset_rng(
        core,
        initial_rng_state,
    )

    core.TRAIN_WEIGHT = original_weights

    # ---------------------------------------------------------
    # Print results.
    # ---------------------------------------------------------

    print()
    print(
        "=== METHOD COMPARISON: NORMAL_TRAFFIC ==="
    )

    print(
        f"{'Method':24s}"
        f"{'Blocks':>8s}"
        f"{'Done':>8s}"
        f"{'Deferred':>10s}"
        f"{'Traffic':>12s}"
        f"{'Overrun':>12s}"
        f"{'Cross%':>9s}"
        f"{'Mean R':>9s}"
        f"{'Min R':>9s}"
    )

    print(
        "-" * 110
    )

    for r in results:
        print(
            f"{r['method']:24s}"
            f"{r['blocks']:8d}"
            f"{r['jobs_done']:8d}"
            f"{r['jobs_deferred']:10d}"
            f"{r['traffic_cost']:12.1f}"
            f"{r['exp_overrun_cost']:12.1f}"
            f"{r['cross_dept_share']:8.1%}"
            f"{r['mean_reliability']:9.2f}"
            f"{r['min_reliability']:9.2f}"
        )

    # ---------------------------------------------------------
    # Save CSV.
    # ---------------------------------------------------------

    output = os.path.join(
        scenarios_dir,
        "method_comparison.csv",
    )

    fields = [
        "method",
        "blocks",
        "jobs_done",
        "jobs_deferred",
        "traffic_cost",
        "traffic_per_job",
        "exp_overrun_cost",
        "cross_dept_blocks",
        "cross_dept_share",
        "mean_reliability",
        "min_reliability",
        "block_utilisation",
    ]

    with open(
        output,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for r in results:
            writer.writerow(
                {
                    field: r.get(
                        field,
                        "",
                    )
                    for field in fields
                }
            )

    print()
    print(
        f"Saved: {output}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )