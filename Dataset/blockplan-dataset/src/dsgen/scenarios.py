"""Planning scenarios.

The infrastructure and the real timetable stay fixed in every scenario. What
varies is maintenance demand, freight volume, duration uncertainty and urgency.
That is the honest way to build scenarios on top of real data: we never invent
a different railway, only a different week on the same railway.
"""
from __future__ import annotations

import numpy as np

SCENARIOS = {
    "NORMAL_TRAFFIC": dict(
        demand_scale=1.0, freight_scale=1.0, uncertainty_scale=1.0,
        urgency_shift=0, backlog=1.0,
        note="Baseline. Real timetable, ordinary maintenance load."),
    "PEAK_TRAFFIC": dict(
        demand_scale=1.0, freight_scale=1.0, uncertainty_scale=1.0,
        urgency_shift=0, backlog=1.0, extra_passenger_scale=1.35,
        note="Festival/peak period: additional passenger services on the real "
             "paths, squeezing the cheap windows."),
    "HEAVY_FREIGHT": dict(
        demand_scale=1.0, freight_scale=2.0, uncertainty_scale=1.0,
        urgency_shift=0, backlog=1.0,
        note="Freight surge. Bites hardest at night, which is where much "
             "maintenance wants to go."),
    "MAINTENANCE_BACKLOG": dict(
        demand_scale=1.8, freight_scale=1.0, uncertainty_scale=1.0,
        urgency_shift=-2, backlog=1.8,
        note="Accumulated backlog after blocks were refused. This is the "
             "scenario in which the reliability constraint actually binds."),
    "URGENT_MAINTENANCE": dict(
        demand_scale=1.0, freight_scale=1.0, uncertainty_scale=1.0,
        urgency_shift=-4, backlog=1.2,
        note="Safety-critical defects with compressed deadlines."),
    "HIGH_DURATION_UNCERTAINTY": dict(
        demand_scale=1.0, freight_scale=1.0, uncertainty_scale=1.8,
        urgency_shift=0, backlog=1.0,
        note="Poorly characterised work. Tests whether the planner trades "
             "bundle size for hand-back reliability."),
    "DISRUPTED_OPERATION": dict(
        demand_scale=1.2, freight_scale=1.3, uncertainty_scale=1.3,
        urgency_shift=-2, backlog=1.3, cancel_window_fraction=0.25,
        note="A quarter of the cheap windows are withdrawn mid-horizon, "
             "forcing a re-plan. Used for the plan-stability metric."),
    "MULTIPLE_DEPARTMENT_REQUESTS": dict(
        demand_scale=1.5, freight_scale=1.0, uncertainty_scale=1.0,
        urgency_shift=0, backlog=1.4,
        note="Higher maintenance demand across all three departments on the "
             "same real sections, so cross-department bundling has more to "
             "gain. The mix is whatever the periodicity-and-asset-inventory "
             "arrival model produces at this rate; it is NOT force-balanced "
             "between ENGG/SNT/TRD, and must not be described as such."),
}


def rows():
    """Scenario table.

    Every key any scenario declares becomes a column, with a blank where a
    scenario does not set it. The previous version took its field names from the
    first row only, so `extra_passenger_scale` and `cancel_window_fraction` were
    written into SCENARIOS, silently dropped from scenarios.csv, and then
    re-invented as hard-coded constants downstream. A declared parameter that
    never reaches the code that needs it is worse than no parameter at all.
    """
    keys = []
    for s in SCENARIOS.values():
        for k in s:
            if k != "note" and k not in keys:
                keys.append(k)
    out = []
    for name, s in SCENARIOS.items():
        r = {"scenario": name}
        r.update({k: s.get(k, "") for k in keys})
        r["note"] = s["note"]
        out.append(r)
    return out


def generate_freight(cor, assumptions, rng, scale=1.0):
    """Freight paths.

    Public timetables carry almost no freight, and Indian Railways audit
    findings record goods trains running without scheduled timings at all. So
    this layer is generated, and it is the largest synthetic component of the
    traffic model. It must never be described as observed traffic.
    """
    f = assumptions["freight"]
    if not f["enabled"]:
        return []
    w = np.array(f["hourly_weight"], dtype=float)
    w = w / w.sum()
    out, n = [], 0
    for s in cor.sections:
        per_day = max(0.0, rng.normal(f["trains_per_day_per_section"]["mean"],
                                      f["trains_per_day_per_section"]["sd"]) * scale)
        k = int(round(per_day))
        for _ in range(k):
            n += 1
            hour = int(rng.choice(24, p=w))
            t = hour * 60 + int(rng.integers(0, 60))
            out.append({
                "train_number": f"F{n:05d}",
                "train_class": "FREIGHT",
                "from_code": s.from_code, "to_code": s.to_code,
                "direction": s.line if s.line in ("UP", "DN") else "DN",
                "enter_min": t,
                "is_synthetic": True,
            })
    return out
