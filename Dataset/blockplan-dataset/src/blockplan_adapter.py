#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import csv
import os
import sys
import time

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
    """Load the authoritative pairing rules.

    Delegates to core.load_pairing_rules so there is one parser and one source
    of truth. core.MANDATORY_PAIRING now starts empty and
    expand_mandatory_pairings raises if nothing was loaded, so a forgotten call
    here fails loudly instead of quietly producing single-department bundles.
    """
    return core.load_pairing_rules(path)


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


def _float_or(value, default):
    """Scenario columns are blank where a scenario does not declare them."""
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_scenarios(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def scenario_jobs_path(dataset_dir, scenario_name):
    return os.path.join(
        dataset_dir, "scenarios", "jobs", f"jobs_{scenario_name}.csv"
    )


def load_scenario_jobs(core, dataset_dir, scenario, section_ids):
    """Maintenance demand for one scenario.

    There is no cloning and no post-hoc mutation of the base jobs here any more.
    Scenario demand is GENERATED, by src/generate_scenario_jobs.py, through the
    same dsgen.demand.generate_jobs the base dataset uses, with the scenario's
    own declared demand_scale, backlog, uncertainty_scale and urgency_shift.
    Additional demand is therefore independent new work with its own section,
    footprint, duration, resource and due date.

    The previous clone-based path produced jobs that shared their original's
    footprint AND its exclusive resource id, so a clone could never be bundled
    with, or even run concurrently with, the job it came from. That is not
    higher demand; it is unschedulable demand, and it distorted exactly the two
    scenarios meant to show the method under load.

    Falls back to the base jobs.csv only if the scenario file has not been
    generated, and says so, rather than silently planning the wrong instance.
    """
    path = scenario_jobs_path(dataset_dir, scenario["scenario"])

    if not os.path.exists(path):
        print(
            f"  WARNING: {os.path.basename(path)} not found; falling back to "
            f"the base jobs.csv. Run generate_scenario_jobs.py to build "
            f"scenario demand properly."
        )
        path = os.path.join(dataset_dir, "processed", "jobs.csv")

    return load_jobs(core, path, section_ids)


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

    scale = _float_or(scenario.get("extra_passenger_scale"), 1.0)

    if scale <= 1.0:
        return trains

    result = list(trains)

    # The scenario note says "additional passenger services on the real paths",
    # so that is what this builds. For each section-line we take the real
    # passenger movements already on it and re-run a fraction of them, offset by
    # half the section headway. Two properties the previous version lacked:
    #
    #   - the extra services follow the real timetable's own shape, so the peak
    #     lands where passenger traffic actually is, instead of a uniform
    #     two-hourly comb that ignores it;
    #   - the count is driven by the declared extra_passenger_scale, which now
    #     reaches this code through scenarios.csv instead of being re-invented
    #     here as a hard-coded 120-minute interval on UP lines only.
    #
    # Deterministic: the paths are taken in timetable order, not sampled.
    freight = {"FREIGHT"}
    by_section = {}

    for train in trains:
        if train.klass in freight:
            continue
        by_section.setdefault(train.section_id, []).append(train)

    headway = {section.id: section.headway_min for section in sections}

    counter = 0

    for section_id in sorted(by_section):

        pool = sorted(
            by_section[section_id],
            key=lambda t: t.sched_min,
        )

        extra = int(round(len(pool) * (scale - 1.0)))

        if extra <= 0:
            continue

        # Spread the chosen paths evenly through the existing pattern.
        step = max(1, len(pool) // extra)
        offset = max(1, headway.get(section_id, 8) // 2)

        for k in range(extra):

            src = pool[(k * step) % len(pool)]

            result.append(
                core.Train(
                    id=f"PEAK_SYN_{counter}",
                    section_id=src.section_id,
                    sched_min=(src.sched_min + offset) % 1440,
                    klass=src.klass,
                    day_mask=src.day_mask,
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

    fraction = _float_or(scenario.get("cancel_window_fraction"), 0.0)

    if fraction <= 0.0:
        return windows

    # Deterministic withdrawal, driven by the fraction the scenario declares
    # rather than a hard-coded modulus. `every` is the reciprocal of the
    # requested fraction, so 0.25 withdraws every 4th window as before, and a
    # different declared fraction now actually changes the behaviour.
    every = max(2, int(round(1.0 / fraction)))

    result = []

    for window in windows:

        signature = (
            window.day
            + window.start_min // 30
            + sum(ord(c) for c in window.section_id)
        )

        if signature % every != 0:
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
def reset_mc_rng(core, saved_state):
    """Reset the Monte Carlo RNG to an identical state."""
    core.RNG.bit_generator.state = copy.deepcopy(saved_state)
def run_method_comparison(core, jobs, trains, sections, horizon):
    """
    Compare B1/B2/B3/B4 against OURS on exactly the same real-data instance.

    All methods receive the same jobs, sections and candidate windows.
    Only the planning strategy changes.
    """
    saved_state = copy.deepcopy(core.RNG.bit_generator.state)
    # Expand mandatory pairings once so every method sees the same job structure.
    jobs = core.expand_mandatory_pairings(jobs)

    # Same candidate supply for every method.
    windows = core.generate_windows(
        sections,
        trains,
        horizon,
        keep_per_day=8,
    )

    # Same bundle universe for B1/B3/B4/OURS.
    bundles = core.enumerate_bundles(
        jobs,
        max_size=5,
    )

    results = []

    # ---------------------------------------------------------
    # B0 — Department-wise, NO reliability filter.
    #      This is the one that represents current practice: nobody computes a
    #      hand-back probability today, so no baseline claiming to be current
    #      practice may apply our chance constraint.
    # ---------------------------------------------------------
    reset_mc_rng(core, saved_state)
    b0, _ = core.baseline_department_wise(
        jobs,
        bundles,
        windows,
        sections,
        horizon,
        reliability_required=False,
    )
    results.append(
        core.evaluate("B0 Dept-wise, no reliability", b0, jobs)
    )

    # ---------------------------------------------------------
    # B1 — Department-wise WITH the reliability filter.
    #      Our method with cross-department bundling switched off. B0 -> B1
    #      isolates the filter; B1 -> OURS isolates the bundling.
    # ---------------------------------------------------------
    reset_mc_rng(core, saved_state)
    b1, _ = core.baseline_department_wise(
        jobs,
        bundles,
        windows,
        sections,
        horizon,
        reliability_required=True,
    )
    results.append(
        core.evaluate("B1 Dept-wise + reliability", b1, jobs)
    )

    # ---------------------------------------------------------
    # B2 — Fixed calendar
    # ---------------------------------------------------------
    reset_mc_rng(core, saved_state)
    b2, _ = core.baseline_fixed_calendar(
        jobs,
        windows,
        sections,
        horizon,
    )
    results.append(
        core.evaluate("B2 Fixed-calendar", b2, jobs)
    )

    # ---------------------------------------------------------
    # B3 — Greedy earliest
    # ---------------------------------------------------------
    reset_mc_rng(core, saved_state)
    b3, _ = core.baseline_greedy_earliest(
        jobs,
        bundles,
        windows,
        horizon,
    )
    results.append(
        core.evaluate("B3 Greedy-earliest", b3, jobs)
    )

    # ---------------------------------------------------------
    # B4 — Bundle-only, reliability disabled
    # ---------------------------------------------------------
    
    # The reset must precede build_columns(), not solve(). build_columns() is
    # the RNG-consuming step (reliability_mc draws); solve() never touches
    # core.RNG -- CP-SAT has its own random_seed. Resetting after the draws
    # left B4 sampling from whatever state B3 happened to leave behind, which
    # is not the isolated, canonical state B0-B3 each get.
    reset_mc_rng(core, saved_state)
    columns_norel = core.build_columns(
        jobs,
        bundles,
        windows,
        theta=core.THETA,
        reliability_required=False,
        mc_samples=1500,
    )
    b4 = core.solve(
        jobs,
        columns_norel,
        sections,
        horizon,
        time_limit_s=60,
    )

    results.append(
        core.evaluate("B4 Bundle-only", b4["blocks"], jobs)
    )

    # ---------------------------------------------------------
    # OURS — reliability-aware optimization
    # ---------------------------------------------------------
    # Same correction as B4 above: reset before the draws, not after them.
    reset_mc_rng(core, saved_state)
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
        horizon,
        time_limit_s=60,
    )

    results.append(
        core.evaluate("OURS", ours["blocks"], jobs)
    )
    reset_mc_rng(core, saved_state)
    return results
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
    # ---------------------------------------------------------
    # METHOD COMPARISON — NORMAL TRAFFIC
    # ---------------------------------------------------------

    normal_scenario = next(
        s for s in scenarios
        if s["scenario"] == "NORMAL_TRAFFIC"
    )

    comparison_jobs, _ = load_scenario_jobs(
        core,
        args.dataset,
        normal_scenario,
        section_ids,
    )

    comparison_trains = list(trains)

    # Apply the same scenario transformations used by the main benchmark.
    comparison_trains = add_peak_passenger_traffic(
        core,
        comparison_trains,
        sections,
        normal_scenario,
    )

    original_weights = apply_freight_scenario(
        core,
        normal_scenario,
    )

    try:
        comparison_results = run_method_comparison(
            core,
            comparison_jobs,
            comparison_trains,
            sections,
            args.horizon,
        )
    finally:
        core.TRAIN_WEIGHT = original_weights

    print("\n=== METHOD COMPARISON: NORMAL_TRAFFIC ===")

    print(
        f"{'Method':24s} "
        f"{'Blocks':>7s} "
        f"{'Done':>7s} "
        f"{'Deferred':>9s} "
        f"{'Traffic':>11s} "
        f"{'Overrun':>11s} "
        f"{'Cross%':>8s} "
        f"{'Mean R':>8s} "
        f"{'Min R':>8s}"
    )

    print("-" * 110)

    for row in comparison_results:
        print(
            f"{row['method']:24s} "
            f"{row['blocks']:7d} "
            f"{row['jobs_done']:7d} "
            f"{row['jobs_deferred']:9d} "
            f"{row['traffic_cost']:11.1f} "
            f"{row['exp_overrun_cost']:11.1f} "
            f"{row['cross_dept_share']:7.1%} "
            f"{row['mean_reliability']:8.2f} "
            f"{row['min_reliability']:8.2f}"
        )

    comparison_path = os.path.join(
        args.dataset,
        "scenarios",
        "method_comparison.csv",
    )

    comparison_fields = [
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
        comparison_path,
        "w",
        newline="",
        encoding="utf-8",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=comparison_fields,
        )
        writer.writeheader()

        for row in comparison_results:
            writer.writerow(
                {
                    field: row.get(field, "")
                    for field in comparison_fields
                }
            )

    print(
        f"\nMethod comparison saved to:\n"
        f"  {comparison_path}"
    )
    print(
        "\n=== SCENARIO BENCHMARK ==="
    )

    for scenario in scenarios:

        name = scenario["scenario"]

        print(
            f"\n--- {name} ---"
        )

        # Scenario demand is generated, not cloned. Same infrastructure and
        # same real timetable in every scenario; only the maintenance
        # programme, the freight weighting and the window supply change.
        scenario_jobs, scenario_skipped = load_scenario_jobs(
            core,
            args.dataset,
            scenario,
            section_ids,
        )
        print(
            f"  jobs={len(scenario_jobs)} "
            f"({scenario_skipped} skipped) from "
            f"{os.path.basename(scenario_jobs_path(args.dataset, name))}"
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
            f"avg_R={result['avg_reliability']:.2f} "
            f"min_R={result['min_reliability']:.2f}"
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
            f"{result['avg_reliability']:7.2f} "
            f"{result['min_reliability']:7.2f}"
        )

    print(
        f"\nBenchmark saved to:\n"
        f"  {output_path}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())