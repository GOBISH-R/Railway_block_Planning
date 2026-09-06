#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import time
from dataclasses import replace

import yaml


def load_config_into_core(core, config_dir):
    with open(os.path.join(config_dir, "assumptions.yaml"), encoding="utf-8") as f:
        A = yaml.safe_load(f)

    with open(os.path.join(config_dir, "rules.yaml"), encoding="utf-8") as f:
        R = yaml.safe_load(f)

    core.THETA = A["reliability"]["theta"]
    core.KAPPA = A["reliability"]["kappa"]
    core.LAMBDA_CLOSE = A["reliability"]["lambda_close_min"]

    core.CLOSING = {
        k: (v["mean"], v["sd"])
        for k, v in A["closing_chain_min"].items()
    }

    core.TRAIN_WEIGHT = dict(A["traffic"]["train_weight"])
    core.OVERRUN_RATE = A["traffic"]["overrun_rate"]
    core.MAX_SPAN_KM = A["bundling"]["max_span_km"]

    core.ALLOWED_BLOCK_LENGTHS = tuple(
        R["block_envelope"]["single_line"]["options_min"]
    )

    core.EXCEPTIONAL_LENGTH = (
        R["block_envelope"]["single_line"]["exceptional_min"]
    )

    return {
        "THETA": core.THETA,
        "KAPPA": core.KAPPA,
        "LAMBDA_CLOSE": core.LAMBDA_CLOSE,
        "CLOSING": core.CLOSING,
        "TRAIN_WEIGHT": f"{len(core.TRAIN_WEIGHT)} classes",
        "OVERRUN_RATE": core.OVERRUN_RATE,
        "MAX_SPAN_KM": core.MAX_SPAN_KM,
        "ALLOWED_BLOCK_LENGTHS": core.ALLOWED_BLOCK_LENGTHS,
        "EXCEPTIONAL_LENGTH": core.EXCEPTIONAL_LENGTH,
    }


def load_pairing_rules_into_core(core, path):
    table = {}

    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            table.setdefault(r["activity"], []).append(
                (
                    r["compelled_dept"],
                    r["companion_activity"],
                    float(r["duration_mean_min"]),
                    float(r["duration_sd_min"]),
                    bool(int(r["must_follow_parent"])),
                )
            )

    core.MANDATORY_PAIRING = table
    return table


def load_sections(core, path):
    sections = []

    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sections.append(
                core.Section(
                    id=r["section_id"],
                    line=r["line"],
                    is_single=bool(int(r["is_single"])),
                    headway_min=int(r["headway_min"]),
                    degraded_factor=float(r["degraded_factor"]) or 1.0,
                )
            )

    return sections


def load_trains(core, path):
    trains = []

    with open(path, encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f)):
            for line in (r["direction"], "SINGLE"):
                section_id = (
                    f"{r['from_code']}-{r['to_code']}-{line}"
                )

                train_class = r["train_class"]

                if train_class not in core.TRAIN_WEIGHT:
                    train_class = "UNKNOWN"

                trains.append(
                    core.Train(
                        id=f"{r['train_number']}#{i}",
                        section_id=section_id,
                        sched_min=int(float(r["enter_min"])),
                        klass=train_class,
                        day_mask=127,
                    )
                )

    return trains


def load_jobs(core, path, section_ids):
    jobs = []
    skipped = 0

    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):

            if r["section_id"] not in section_ids:
                skipped += 1
                continue

            jobs.append(
                core.Job(
                    id=r["job_id"],
                    dept=r["dept"],
                    activity=r["activity"],
                    section_id=r["section_id"],
                    km_from=float(r["km_from"]),
                    km_to=float(r["km_to"]),
                    needs_T=bool(int(r["needs_T"])),
                    needs_P=bool(int(r["needs_P"])),
                    needs_D=bool(int(r["needs_D"])),
                    needs_train_movements=bool(
                        int(r["needs_train_movements"])
                    ),
                    needs_live_ohe=bool(int(r["needs_live_ohe"])),
                    dur_mean=float(r["duration_mean_min"]),
                    dur_sd=float(r["duration_sd_min"]),
                    resources=tuple(
                        x for x in (r["resources"] or "").split("|")
                        if x
                    ),
                    due_day=int(r["due_day"]),
                    criticality=float(r["criticality"]),
                )
            )

    return jobs, skipped


def load_scenarios(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clone_jobs(jobs, target_count):
    """Increase maintenance demand by duplicating existing job patterns."""

    if target_count <= len(jobs):
        return list(jobs)

    result = list(jobs)
    original = list(jobs)

    copy_number = 1

    while len(result) < target_count:

        for job in original:

            if len(result) >= target_count:
                break

            result.append(
                replace(
                    job,
                    id=f"{job.id}_D{copy_number}",
                )
            )

            copy_number += 1

    return result


def apply_job_scenario(jobs, scenario):
    """
    Apply maintenance-side scenario changes.

    demand_scale:
        increases the number of maintenance requests.

    uncertainty_scale:
        increases duration uncertainty.

    urgency_shift:
        moves due dates earlier when negative.
    """

    demand_scale = float(scenario["demand_scale"])
    uncertainty_scale = float(scenario["uncertainty_scale"])
    urgency_shift = int(float(scenario["urgency_shift"]))

    target_count = max(
        len(jobs),
        int(round(len(jobs) * demand_scale)),
    )

    jobs = clone_jobs(jobs, target_count)

    if uncertainty_scale != 1.0:
        jobs = [
            replace(
                job,
                dur_sd=job.dur_sd * uncertainty_scale,
            )
            for job in jobs
        ]

    if urgency_shift != 0:
        jobs = [
            replace(
                job,
                due_day=max(
                    0,
                    job.due_day + urgency_shift,
                ),
            )
            for job in jobs
        ]

    return jobs


def apply_freight_scenario(core, scenario):
    """
    Increase the cost of freight traffic when the scenario requests it.

    The existing core traffic model already uses TRAIN_WEIGHT, so this
    changes the actual objective rather than merely changing a label.
    """

    freight_scale = float(scenario["freight_scale"])

    original_weights = dict(core.TRAIN_WEIGHT)

    if freight_scale != 1.0:

        new_weights = dict(original_weights)

        for klass in new_weights:

            name = klass.upper()

            if (
                "FREIGHT" in name
                or "GOODS" in name
                or "GDS" in name
            ):
                new_weights[klass] *= freight_scale

        core.TRAIN_WEIGHT = new_weights

    return original_weights


def add_peak_passenger_traffic(core, trains, sections, scenario):
    """
    Add synthetic passenger movements for PEAK_TRAFFIC.

    These are explicitly synthetic scenario movements; the base timetable
    remains unchanged.
    """

    if scenario["scenario"] != "PEAK_TRAFFIC":
        return trains

    result = list(trains)

    counter = 0

    for section in sections:

        if not section.id.endswith("-UP"):
            continue

        parts = section.id.rsplit("-", 1)[0]

        # Convert A-B-UP into A-B.
        if "-" not in parts:
            continue

        for start in range(360, 1380, 120):

            result.append(
                core.Train(
                    id=f"PEAK_SYN_{counter}",
                    section_id=section.id,
                    sched_min=start,
                    klass="PASSENGER",
                    day_mask=127,
                )
            )

            counter += 1

    return result


def remove_disrupted_windows(windows, scenario):
    """
    Withdraw a deterministic subset of candidate windows for the
    DISRUPTED_OPERATION scenario.

    This models temporary loss of block availability.
    """

    if scenario["scenario"] != "DISRUPTED_OPERATION":
        return windows

    result = []

    for window in windows:

        # Deterministic rule: withdraw roughly 25% of windows.
        signature = (
            window.day
            + window.start_min // 30
            + sum(ord(c) for c in window.section_id)
        )

        if signature % 4 != 0:
            result.append(window)

    return result


def run_optimizer(
    core,
    jobs,
    trains,
    sections,
    horizon,
    scenario,
):
    """
    Run the unchanged optimisation model on scenario-adjusted inputs.
    """

    jobs = core.expand_mandatory_pairings(jobs)

    t0 = time.perf_counter()

    bundles = core.enumerate_bundles(
        jobs,
        max_size=5,
    )

    enum_seconds = time.perf_counter() - t0

    windows = core.generate_windows(
        sections,
        trains,
        horizon,
        keep_per_day=8,
    )

    windows = remove_disrupted_windows(
        windows,
        scenario,
    )

    t0 = time.perf_counter()

    columns = core.build_columns(
        jobs,
        bundles,
        windows,
        theta=core.THETA,
        mc_samples=1500,
    )

    column_seconds = time.perf_counter() - t0

    result = core.solve(
        jobs,
        columns,
        sections,
        horizon,
        time_limit_s=60,
    )

    index = {
        job.id: job
        for job in jobs
    }

    cross_department = sum(
        1
        for block in result["blocks"]
        if len(
            {
                index[job_id].dept
                for job_id in block.job_ids
            }
        ) > 1
    )

    traffic_cost = sum(
        block.window.traffic_cost
        for block in result["blocks"]
    )

    reliability = [
        block.reliability
        for block in result["blocks"]
    ]

    return {
        "status": result["status"],
        "seconds": result["seconds"],
        "jobs_after_pairing": len(jobs),
        "bundles": len(bundles),
        "windows": len(windows),
        "columns": len(columns),
        "blocks": len(result["blocks"]),
        "deferred": len(result["deferred"]),
        "cross_department": cross_department,
        "cross_department_pct": (
            cross_department /
            max(1, len(result["blocks"]))
        ),
        "traffic_cost": traffic_cost,
        "avg_reliability": (
            sum(reliability) / len(reliability)
            if reliability else 0.0
        ),
        "min_reliability": (
            min(reliability)
            if reliability else 0.0
        ),
        "enum_seconds": enum_seconds,
        "column_seconds": column_seconds,
    }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dataset",
        default="../dataset",
    )

    parser.add_argument(
        "--config",
        default="../config",
    )

    parser.add_argument(
        "--core",
        required=True,
    )

    parser.add_argument(
        "--horizon",
        type=int,
        default=14,
    )

    parser.add_argument(
        "--max-jobs",
        type=int,
        default=0,
    )

    args = parser.parse_args()

    # ---------------------------------------------------------
    # Import core
    # ---------------------------------------------------------

    sys.path.insert(
        0,
        os.path.abspath(args.core),
    )

    import core

    # ---------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------

    print("=== config -> core.py constants ===")

    for key, value in load_config_into_core(
        core,
        args.config,
    ).items():

        print(
            f"  {key:24s} {value}"
        )

    processed = os.path.join(
        args.dataset,
        "processed",
    )

    # ---------------------------------------------------------
    # Pairing rules
    # ---------------------------------------------------------

    rules = load_pairing_rules_into_core(
        core,
        os.path.join(
            processed,
            "pairing_rules.csv",
        ),
    )

    print(
        f"\n=== pairing rules from CSV: "
        f"{sum(len(v) for v in rules.values())} "
        f"rows over {len(rules)} activities ==="
    )

    for activity, values in rules.items():

        for dept, companion, mean, sd, must_follow in values:

            print(
                f"  {activity:22s} compels "
                f"{dept:4s} "
                f"{companion:22s} "
                f"{mean:5.0f}+-{sd:<4.0f}"
                f"{'  (must follow)' if must_follow else ''}"
            )

    # ---------------------------------------------------------
    # Load base dataset
    # ---------------------------------------------------------

    sections = load_sections(
        core,
        os.path.join(
            processed,
            "sections.csv",
        ),
    )

    section_ids = {
        section.id
        for section in sections
    }

    trains = load_trains(
        core,
        os.path.join(
            processed,
            "movements.csv",
        ),
    )

    trains = [
        train
        for train in trains
        if train.section_id in section_ids
    ]

    base_jobs, skipped = load_jobs(
        core,
        os.path.join(
            processed,
            "jobs.csv",
        ),
        section_ids,
    )

    if args.max_jobs:
        base_jobs = base_jobs[:args.max_jobs]

    print("\n=== dataset loaded ===")

    print(
        f"  {len(sections)} section-lines, "
        f"{len(trains)} train movements, "
        f"{len(base_jobs)} jobs "
        f"({skipped} skipped)"
    )

    # ---------------------------------------------------------
    # Scenarios
    # ---------------------------------------------------------

    scenario_path = os.path.join(
        args.dataset,
        "scenarios",
        "scenarios.csv",
    )

    scenarios = load_scenarios(
        scenario_path,
    )

    print(
        f"\n=== scenarios loaded: "
        f"{len(scenarios)} ==="
    )

    # ---------------------------------------------------------
    # Benchmark
    # ---------------------------------------------------------

    results = []

    print(
        "\n=== SCENARIO BENCHMARK ==="
    )

    for scenario in scenarios:

        name = scenario["scenario"]

        print(
            f"\n--- {name} ---"
        )

        # Start every scenario from the same base data.
        scenario_jobs = apply_job_scenario(
            list(base_jobs),
            scenario,
        )

        scenario_trains = list(trains)

        # Peak traffic adds synthetic passenger movements.
        scenario_trains = add_peak_passenger_traffic(
            core,
            scenario_trains,
            sections,
            scenario,
        )

        # Freight scenario changes actual traffic weights.
        original_weights = apply_freight_scenario(
            core,
            scenario,
        )

        try:

            result = run_optimizer(
                core,
                scenario_jobs,
                scenario_trains,
                sections,
                args.horizon,
                scenario,
            )

        finally:

            # Never allow one scenario to affect the next one.
            core.TRAIN_WEIGHT = original_weights

        result["scenario"] = name
        result["demand_scale"] = scenario["demand_scale"]
        result["freight_scale"] = scenario["freight_scale"]
        result["uncertainty_scale"] = scenario["uncertainty_scale"]
        result["urgency_shift"] = scenario["urgency_shift"]

        results.append(result)

        print(
            f"  {result['status']} "
            f"in {result['seconds']:.2f}s"
        )

        print(
            f"  jobs={result['jobs_after_pairing']} "
            f"blocks={result['blocks']} "
            f"deferred={result['deferred']}"
        )

        print(
            f"  cross-dept="
            f"{result['cross_department']}/"
            f"{result['blocks']} "
            f"({result['cross_department_pct']:.0%})"
        )

        print(
            f"  traffic={result['traffic_cost']:.1f} "
            f"avg_R={result['avg_reliability']:.3f} "
            f"min_R={result['min_reliability']:.3f}"
        )

    # ---------------------------------------------------------
    # Save results
    # ---------------------------------------------------------

    output_path = os.path.join(
        args.dataset,
        "scenarios",
        "benchmark_results.csv",
    )

    fields = [
        "scenario",
        "status",
        "demand_scale",
        "freight_scale",
        "uncertainty_scale",
        "urgency_shift",
        "jobs_after_pairing",
        "bundles",
        "windows",
        "columns",
        "blocks",
        "deferred",
        "cross_department",
        "cross_department_pct",
        "traffic_cost",
        "avg_reliability",
        "min_reliability",
        "seconds",
        "enum_seconds",
        "column_seconds",
    ]

    with open(
        output_path,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for result in results:

            writer.writerow(
                {
                    field: result.get(
                        field,
                        "",
                    )
                    for field in fields
                }
            )

    # ---------------------------------------------------------
    # Print final table
    # ---------------------------------------------------------

    print(
        "\n=== FINAL SCENARIO COMPARISON ==="
    )

    print(
        f"{'Scenario':28s} "
        f"{'Jobs':>7s} "
        f"{'Blocks':>7s} "
        f"{'Deferred':>9s} "
        f"{'Cross%':>8s} "
        f"{'Traffic':>10s} "
        f"{'Avg R':>7s} "
        f"{'Min R':>7s}"
    )

    print("-" * 95)

    for result in results:

        print(
            f"{result['scenario']:28s} "
            f"{result['jobs_after_pairing']:7d} "
            f"{result['blocks']:7d} "
            f"{result['deferred']:9d} "
            f"{result['cross_department_pct']:7.0%} "
            f"{result['traffic_cost']:10.1f} "
            f"{result['avg_reliability']:7.3f} "
            f"{result['min_reliability']:7.3f}"
        )

    print(
        f"\nBenchmark saved to:\n"
        f"  {output_path}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())