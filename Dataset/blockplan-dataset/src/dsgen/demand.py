"""Synthetic maintenance demand, placed on the real network.

The generation model is deliberately not `random.randint`. Jobs arrive as a
Poisson process whose rate is derived from an asset inventory and a maintenance
periodicity:

    expected jobs of activity a in the horizon
        = (number of assets of a's type) x (horizon days) / (periodicity days)

and the realised count is Poisson around that. Two consequences that matter:

  - the mix of activities is a consequence of periodicity and asset counts, not
    of an arbitrary weighting we chose. Turnout work is common because there are
    many turnouts and they come round often; deep screening is rare because its
    cycle is measured in years.
  - because arrivals in a Poisson window are uniform, due dates in the horizon
    are uniform *by construction* rather than by assumption.

The asset counts and the periodicities are themselves assumptions (see
config/assumptions.yaml and config/activities.yaml). The METHOD is defensible;
the NUMBERS are declared. Both statements need to be made together.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np


@dataclass
class Job:
    job_id: str
    dept: str
    activity: str
    section_id: str
    location_desc: str
    km_from: float
    km_to: float
    needs_T: int
    needs_P: int
    needs_D: int
    needs_train_movements: int
    needs_live_ohe: int
    duration_mean_min: float
    duration_sd_min: float
    duration_min_min: float
    duration_max_min: float
    min_block_min: int
    resources: str
    due_day: int
    criticality: float
    priority: str
    uncertainty_level: str
    provenance: str


def _trunc_lognormal(rng, mean, sd, lo, hi, size=None):
    sigma = np.sqrt(np.log(1.0 + (sd / mean) ** 2))
    mu = np.log(mean) - 0.5 * sigma ** 2
    x = rng.lognormal(mu, sigma, size)
    return np.clip(x, lo, hi)


def build_asset_inventory(cor, assumptions):
    """Count maintainable assets on each real section-line.

    TRACK_KM and OHE_KM scale with the real section length. TURNOUT and
    SIGNAL_POINT live at stations, and a station's assets are split between the
    section-lines it bounds, placed near the station end of the section.
    """
    a = assumptions["assets"]
    inv = {}
    st_by_code = {s.code: s for s in cor.stations}
    adj = {}
    for s in cor.sections:
        adj.setdefault(s.from_code, []).append(s)
        adj.setdefault(s.to_code, []).append(s)

    for s in cor.sections:
        inv[s.section_id] = {
            "TRACK_KM": s.length_km,
            "OHE_KM": s.length_km * a["ohe_km_per_track_km"] if s.electrified else 0.0,
            "TURNOUT": 0.0,
            "SIGNAL_POINT": 0.0,
            "_len": s.length_km,
        }
    for code, st in st_by_code.items():
        kind = "junction" if st.is_junction else "regular"
        n_to = a["turnouts_per_station"][kind]
        n_sp = a["signal_points_per_station"][kind]
        touching = adj.get(code, [])
        if not touching:
            continue
        for s in touching:
            inv[s.section_id]["TURNOUT"] += n_to / len(touching)
            inv[s.section_id]["SIGNAL_POINT"] += n_sp / len(touching)
    return inv


def generate_jobs(cor, activities, assumptions, horizon_days, seed,
                  backlog_multiplier=None, demand_scale=1.0,
                  uncertainty_scale=1.0, target_jobs=None):
    rng = np.random.default_rng(seed)
    inv = build_asset_inventory(cor, assumptions)
    dem = assumptions["demand"]
    bm = backlog_multiplier if backlog_multiplier is not None else dem["backlog_multiplier"]
    fleets = assumptions["resources"]
    cd = dem["criticality_defect_multiplier"]

    acts = {a["id"]: a for a in activities["activities"]}
    rate_scale = bm * demand_scale
    if target_jobs:
        base = _expected_total(inv, acts, horizon_days)
        rate_scale = max(0.05, target_jobs / base) if base > 0 else 1.0

    jobs, n = [], 0
    for sec in cor.sections:
        assets = inv[sec.section_id]
        for aid, act in acts.items():
            count_assets = assets.get(act["asset"], 0.0)
            if count_assets <= 0:
                continue
            lam = count_assets * horizon_days / act["periodicity_days"] * rate_scale
            k = rng.poisson(lam)
            for _ in range(int(k)):
                n += 1
                jobs.append(_make_job(rng, n, sec, act, assets["_len"], fleets,
                                      horizon_days, bm, cd, uncertainty_scale))
    jobs.sort(key=lambda j: (j.due_day, j.job_id))
    return jobs


def _expected_total(inv, acts, horizon_days):
    tot = 0.0
    for assets in inv.values():
        for act in acts.values():
            c = assets.get(act["asset"], 0.0)
            if c > 0:
                tot += c * horizon_days / act["periodicity_days"]
    return tot


def _make_job(rng, n, sec, act, sec_len, fleets, horizon_days, backlog,
              cd, uncertainty_scale):
    fp = max(0.02, float(_trunc_lognormal(rng, act["footprint_km"]["mean"],
                                          act["footprint_km"]["sd"],
                                          0.02, max(0.05, sec_len))))
    fp = min(fp, max(0.05, sec_len * 0.9))
    km_from = float(rng.uniform(0, max(0.001, sec_len - fp)))
    km_to = round(km_from + fp, 3)

    d = act["duration_min"]
    mean = float(_trunc_lognormal(rng, d["mean"], d["sd"] * 0.5, d["min"], d["max"]))
    sd = float(d["sd"] * uncertainty_scale * rng.uniform(0.8, 1.25))

    # Poisson arrivals are uniform in the window; an overdue tail is added in
    # proportion to the backlog multiplier.
    overdue_tail = int(round(7 * max(0.0, backlog - 1.0)))
    due = int(rng.integers(-overdue_tail, horizon_days + 1)) if overdue_tail else \
        int(rng.integers(0, horizon_days + 1))

    crit = act["criticality_base"] * float(np.clip(
        rng.normal(cd["mean"], cd["sd"]), cd["min"], cd["max"]))
    prio = "URGENT" if (due <= 0 or crit >= 2.0) else ("HIGH" if crit >= 1.4 else "NORMAL")
    unc = "HIGH" if sd / mean > 0.28 else ("LOW" if sd / mean < 0.15 else "MEDIUM")

    rc = act["resource_class"]
    inst = int(rng.integers(0, max(1, fleets.get(rc, 1))))
    prot = act["protection"]

    return Job(
        job_id=f"J{n:05d}", dept=act["dept"], activity=act["id"],
        section_id=sec.section_id,
        location_desc=f"{sec.from_code}-{sec.to_code} {sec.line} km {km_from:.2f}",
        km_from=round(km_from, 3), km_to=km_to,
        needs_T=int(bool(prot["T"])), needs_P=int(bool(prot["P"])),
        needs_D=int(bool(prot["D"])),
        needs_train_movements=int(bool(act.get("needs_train_movements", False))),
        needs_live_ohe=int(bool(act.get("needs_live_ohe", False))),
        duration_mean_min=round(mean, 1), duration_sd_min=round(sd, 1),
        duration_min_min=float(d["min"]), duration_max_min=float(d["max"]),
        min_block_min=int(act["min_block_min"]),
        resources=f"{rc}_{inst}", due_day=due, criticality=round(crit, 3),
        priority=prio, uncertainty_level=unc,
        provenance="D:poisson_from_periodicity",
    )


def generate_block_requests(jobs, rng, horizon_days):
    """Synthesise the block request each department would raise for each job.

    We do NOT have BDMS data and this is not a reconstruction of it. It is the
    demand-side artefact our planner consumes, generated from the jobs so that
    the pipeline has a realistic input shape.
    """
    pref_hour = {"ENGG": (9, 14), "SNT": (22, 4), "TRD": (0, 5)}
    reason = {"URGENT": "defect requiring early attention",
              "HIGH": "schedule due", "NORMAL": "planned periodic maintenance"}
    out = []
    for j in jobs:
        lo, hi = pref_hour[j.dept]
        h = int(rng.integers(lo, hi)) % 24 if lo < hi else \
            int(rng.integers(lo, hi + 24)) % 24
        pref_day = int(np.clip(j.due_day - rng.integers(0, 3), 0, horizon_days))
        req = int(np.ceil((j.duration_mean_min + 1.0 * j.duration_sd_min) / 30.0) * 30)
        out.append({
            "request_id": f"R{j.job_id[1:]}",
            "job_id": j.job_id,
            "department": j.dept,
            "preferred_date": pref_day,
            "preferred_window_start_min": h * 60,
            "minimum_duration_min": max(60, int(j.duration_mean_min)),
            "requested_duration_min": max(j.min_block_min, req),
            "protection_type": "".join(c for c, f in
                                       (("T", j.needs_T), ("P", j.needs_P), ("D", j.needs_D)) if f) or "NONE",
            "deadline_day": j.due_day,
            "priority": j.priority,
            "reason": reason[j.priority],
            "provenance": "D:synthesised_from_job",
        })
    return out


def generate_execution(jobs, assumptions, seed):
    """Stochastic realisations of actual working time.

    PLANNING data and EVALUATION data are separated on purpose. The planner
    sees duration_mean_min and duration_sd_min. It never sees this file. A
    realisation is what actually happened on one simulated occasion, and it is
    what the hand-back success rate is scored against.
    """
    ex = assumptions["execution"]
    rng = np.random.default_rng(seed + ex["realisation_seed_offset"])
    rows = []
    for r in range(ex["n_realisations"]):
        for j in jobs:
            actual = float(_trunc_lognormal(rng, j.duration_mean_min, j.duration_sd_min,
                                            j.duration_min_min, j.duration_max_min))
            rows.append({"realisation": r, "job_id": j.job_id,
                         "actual_duration_min": round(actual, 1)})
    return rows


def job_rows(jobs):
    return [asdict(j) for j in jobs]
