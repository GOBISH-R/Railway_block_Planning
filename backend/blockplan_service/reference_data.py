"""Read-only reference data: corridor geography, scenarios, demand, traffic,
and the frozen comparison artefacts.

Added in Phase 3, alongside the frontend that needs them. API_CONTRACT.md
scoped all five of these in Phase 0; Phase 2 deliberately left them out of its
brief ("explainability"), noting they would be built "for the phase that needs
them" -- this is that phase.

None of this contains planning or optimisation logic. Every function here
either reads a frozen CSV directly, or reads from PlanningContext, which itself
only reuses the existing blockplan_adapter loaders. Nothing calls
core.enumerate_bundles, core.build_columns or core.solve.
"""
from __future__ import annotations

import csv
from typing import Any

from . import paths
from .context import PlanningContext


def corridor_payload(context: PlanningContext) -> dict[str, Any]:
    """GET /corridor. Static geography; instant."""
    return {
        "stations": [dict(s) for s in context.stations],
        "sections": [dict(context.section_meta[s.id]) for s in context.sections],
    }


def scenarios_payload(context: PlanningContext) -> dict[str, Any]:
    """GET /scenarios. The eight scenarios and their declared parameters."""
    scenarios = []
    for name in context.scenario_names:
        row = context.scenario(name)
        scenarios.append({
            "name": name,
            "demand_scale": float(row["demand_scale"]),
            "freight_scale": float(row["freight_scale"]),
            "uncertainty_scale": float(row["uncertainty_scale"]),
            "urgency_shift": int(row["urgency_shift"]),
            "backlog": float(row["backlog"]),
            "extra_passenger_scale": _float_or_none(row.get("extra_passenger_scale")),
            "cancel_window_fraction": _float_or_none(row.get("cancel_window_fraction")),
            "note": row["note"],
            "realised_job_count": context.base_job_count(name),
        })
    return {"scenarios": scenarios}


def demand_payload(context: PlanningContext, scenario: str) -> dict[str, Any]:
    """GET /demand?scenario=X.

    Reads the scenario's job CSV directly rather than through
    context.jobs_for(), because `priority` and `uncertainty_level` are UI-only
    labels core.Job does not carry (the dataset's own documentation is explicit
    that the optimiser must not consume them -- using them would double-count
    urgency the model already has via criticality and due_day).
    """
    if not context.has_scenario(scenario):
        raise KeyError(scenario)
    path = paths.scenario_jobs_csv(scenario)
    jobs = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["section_id"] not in context.section_ids:
                continue
            jobs.append({
                "job_id": row["job_id"],
                "dept": row["dept"],
                "activity": row["activity"],
                "section_id": row["section_id"],
                "km_from": float(row["km_from"]),
                "km_to": float(row["km_to"]),
                "needs_T": row["needs_T"] == "1",
                "needs_P": row["needs_P"] == "1",
                "needs_D": row["needs_D"] == "1",
                "needs_train_movements": row["needs_train_movements"] == "1",
                "needs_live_ohe": row["needs_live_ohe"] == "1",
                "duration_mean_min": float(row["duration_mean_min"]),
                "duration_sd_min": float(row["duration_sd_min"]),
                "due_day": int(row["due_day"]),
                "criticality": float(row["criticality"]),
                "priority": row["priority"],
                "uncertainty_level": row["uncertainty_level"],
                "resources": [r for r in row["resources"].split("|") if r],
            })
    return {"scenario": scenario, "jobs": jobs}


def traffic_payload(context: PlanningContext, scenario: str,
                    section_id: str | None = None) -> dict[str, Any]:
    """GET /traffic?scenario=X&section_id=Y.

    Real movements are read straight from movements.csv. PEAK_TRAFFIC's
    synthetic additions are computed by the existing
    add_peak_passenger_traffic() (reused, not reimplemented) and converted back
    to display rows -- that function returns core.Train objects (id,
    section_id, sched_min, klass, day_mask), not the richer row shape
    movements.csv carries, so the synthetic ones are given a synthesised
    train_number and their direction/station codes read back from the section
    they sit on.
    """
    if not context.has_scenario(scenario):
        raise KeyError(scenario)

    movements: list[dict[str, Any]] = []
    with open(paths.MOVEMENTS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            movements.append({
                "train_number": row["train_number"],
                "train_class": row["train_class"],
                "from_code": row["from_code"],
                "to_code": row["to_code"],
                "direction": row["direction"],
                "enter_min": int(row["enter_min"]),
                "is_synthetic": row["is_synthetic"].strip().lower() in ("1", "true"),
                "section_id": f"{row['from_code']}-{row['to_code']}-{row['direction']}",
            })

    base_ids = {t.id for t in context.trains}
    scenario_trains = context.trains_for(scenario)
    section_by_id = {s.id: s for s in context.sections}
    for train in scenario_trains:
        if train.id in base_ids:
            continue  # already covered by the real movements above
        parts = train.section_id.split("-")
        from_code, to_code = (parts[0], parts[1]) if len(parts) >= 2 else (train.section_id, "")
        section = section_by_id.get(train.section_id)
        movements.append({
            "train_number": train.id,
            "train_class": train.klass,
            "from_code": from_code,
            "to_code": to_code,
            "direction": section.line if section else "",
            "enter_min": train.sched_min,
            "is_synthetic": True,
            "section_id": train.section_id,
        })

    if section_id:
        movements = [m for m in movements if m["section_id"] == section_id]

    return {"scenario": scenario, "movements": movements}


def comparison_payload() -> dict[str, Any]:
    """GET /comparison. Serves the three frozen benchmark artefacts as-is.

    A reader, not a runner: every number here must match its source CSV
    exactly, with no rounding invented in this layer.
    """
    return {
        "method_comparison": _read_csv_numeric(paths.METHOD_COMPARISON_CSV),
        "execution_scoring_summary": _read_csv_numeric(paths.EXECUTION_SCORING_SUMMARY_CSV),
        "benchmark_results": _read_csv_numeric(paths.BENCHMARK_RESULTS_CSV),
    }


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _read_csv_numeric(path: str) -> list[dict[str, Any]]:
    """Read a CSV, converting numeric-looking strings to int/float.

    Kept generic and reused across all three comparison files rather than
    hand-writing three near-identical parsers, since all three files consist of
    one string column (method/scenario/status) followed by columns that are
    always numeric.
    """
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row: dict[str, Any] = {}
            for key, value in raw.items():
                row[key] = _coerce_number(value)
            rows.append(row)
    return rows


def _coerce_number(value: str) -> Any:
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
