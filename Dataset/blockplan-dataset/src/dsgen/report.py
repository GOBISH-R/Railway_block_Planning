"""Dataset quality report and figures."""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

import numpy as np


def stats(ds) -> dict:
    st, sec, jobs = ds["stations"], ds["sections"], ds["jobs"]
    mov = ds["movements"]
    real = [m for m in mov if not m["is_synthetic"]]
    synth = [m for m in mov if m["is_synthetic"]]
    phys = {(s["from_station_code"], s["to_station_code"]) for s in sec}
    route_km = sum(s["length_km"] for s in sec if s["line"] in ("UP", "SINGLE"))
    durs = np.array([j["duration_mean_min"] for j in jobs]) if jobs else np.array([0])
    dues = np.array([j["due_day"] for j in jobs]) if jobs else np.array([0])
    hourly = Counter(m["enter_min"] // 60 for m in mov)
    per_line = Counter(m["from_code"] + "-" + m["to_code"] + "-" + m["direction"] for m in mov)

    return {
        "study_area": ds["meta"]["study_area"],
        "source_mode": ds["meta"]["source_mode"],
        "source_hashes": ds["meta"]["source_hashes"],
        "seed": ds["meta"]["seed"],
        "horizon_days": ds["meta"]["horizon_days"],
        "n_stations": len(st),
        "n_junctions": sum(1 for s in st if s["is_junction"]),
        "n_physical_sections": len(phys),
        "n_section_lines": len(sec),
        "route_km": round(route_km, 2),
        "published_distance_km": ds["meta"].get("published_distance_km"),
        "distance_scale_factor": round(ds["meta"].get("scale_factor", 1.0), 4),
        "track_source_counts": dict(Counter(s["track_source"] for s in sec)),
        "n_real_trains": len({m["train_number"] for m in real}),
        "n_synthetic_freight_paths": len({m["train_number"] for m in synth}),
        "real_movements_per_day": len(real),
        "synthetic_movements_per_day": len(synth),
        "busiest_section_line_movements": max(per_line.values()) if per_line else 0,
        "peak_hour": max(hourly, key=hourly.get) if hourly else None,
        "peak_hour_movements": max(hourly.values()) if hourly else 0,
        "quietest_hour": min(hourly, key=hourly.get) if hourly else None,
        "mean_headway_min": round(float(np.mean([s["headway_min"] for s in sec])), 1),
        "n_jobs": len(jobs),
        "jobs_by_dept": dict(Counter(j["dept"] for j in jobs)),
        "jobs_by_activity": dict(Counter(j["activity"] for j in jobs).most_common()),
        "jobs_by_protection": dict(Counter(
            "".join(c for c, f in (("T", j["needs_T"]), ("P", j["needs_P"]),
                                   ("D", j["needs_D"])) if f) or "NONE"
            for j in jobs)),
        "jobs_by_priority": dict(Counter(j["priority"] for j in jobs)),
        "jobs_by_uncertainty": dict(Counter(j["uncertainty_level"] for j in jobs)),
        "sections_with_jobs": len({j["section_id"] for j in jobs}),
        "class_d_jobs": sum(1 for j in jobs
                            if j["needs_train_movements"] or j["needs_live_ohe"]),
        "duration_min_mean_p50_p95_max": [
            round(float(durs.min()), 1), round(float(durs.mean()), 1),
            round(float(np.percentile(durs, 50)), 1),
            round(float(np.percentile(durs, 95)), 1), round(float(durs.max()), 1)],
        "due_day_min_p50_max": [int(dues.min()), int(np.percentile(dues, 50)),
                                int(dues.max())],
        "overdue_jobs": int((dues < 0).sum()),
        "n_pairing_rules": len(ds["pairing_rules"]),
        "n_scenarios": len(ds["scenarios"]),
        "n_block_requests": len(ds["block_requests"]),
        "n_execution_rows": len(ds["execution"]),
    }


def figures(ds, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)
    st, sec, jobs, mov = ds["stations"], ds["sections"], ds["jobs"], ds["movements"]
    made = []

    def save(fig, name):
        p = os.path.join(outdir, name)
        fig.tight_layout()
        fig.savefig(p, dpi=130)
        plt.close(fig)
        made.append(p)

    # 1 network map with stations
    fig, ax = plt.subplots(figsize=(7, 5))
    lons = [s["longitude"] for s in sorted(st, key=lambda x: x["seq"])]
    lats = [s["latitude"] for s in sorted(st, key=lambda x: x["seq"])]
    ax.plot(lons, lats, "-", lw=2, color="#15616D", zorder=1)
    jn = [s for s in st if s["is_junction"]]
    ax.scatter([s["longitude"] for s in st], [s["latitude"] for s in st],
               s=26, color="#15616D", zorder=2, label="station")
    if jn:
        ax.scatter([s["longitude"] for s in jn], [s["latitude"] for s in jn],
                   s=90, facecolors="none", edgecolors="#A83A2E", lw=1.6,
                   zorder=3, label="junction")
    for s in st:
        ax.annotate(s["station_code"], (s["longitude"], s["latitude"]),
                    fontsize=6.5, xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.set_title(f"Corridor network — {ds['meta']['study_area']}", fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=.25)
    save(fig, "01_network_map.png")

    # 2 train density by hour
    fig, ax = plt.subplots(figsize=(7, 3.2))
    hours = np.arange(24)
    realh = Counter(m["enter_min"] // 60 for m in mov if not m["is_synthetic"])
    synh = Counter(m["enter_min"] // 60 for m in mov if m["is_synthetic"])
    ax.bar(hours, [realh.get(h, 0) for h in hours], color="#15616D", label="real timetable")
    ax.bar(hours, [synh.get(h, 0) for h in hours],
           bottom=[realh.get(h, 0) for h in hours], color="#9A6B00",
           label="synthetic freight")
    ax.set_xlabel("hour of day"); ax.set_ylabel("section movements")
    ax.set_title("Traffic density by hour", fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=.25, axis="y")
    save(fig, "02_train_density.png")

    # 3 jobs mapped onto sections
    fig, ax = plt.subplots(figsize=(7, 5))
    order = {s["station_code"]: s["seq"] for s in st}
    off = {}
    cum, base = 0.0, {}
    for s in sorted(st, key=lambda x: x["seq"])[:-1]:
        nxt = [x for x in sec if x["from_station_code"] == s["station_code"]]
        base[s["station_code"]] = cum
        cum += nxt[0]["length_km"] if nxt else 0
    col = {"ENGG": "#15616D", "SNT": "#A83A2E", "TRD": "#9A6B00"}
    lane = {"UP": 0.12, "DN": -0.12, "SINGLE": 0.0}
    for j in jobs:
        s = next((x for x in sec if x["section_id"] == j["section_id"]), None)
        if not s:
            continue
        x0 = base.get(s["from_station_code"], 0) + j["km_from"]
        x1 = base.get(s["from_station_code"], 0) + j["km_to"]
        y = lane.get(s["line"], 0) + {"ENGG": 0.03, "SNT": 0, "TRD": -0.03}[j["dept"]]
        ax.plot([x0, x1], [y, y], lw=2.2, color=col[j["dept"]], alpha=.55)
    for s in st:
        ax.axvline(base.get(s["station_code"], cum), color="#A9B5B4", lw=.7, zorder=0)
    for d, c in col.items():
        ax.plot([], [], color=c, lw=2.5, label=d)
    ax.set_yticks([0.12, 0, -0.12]); ax.set_yticklabels(["UP", "SINGLE", "DN"])
    ax.set_xlabel("kilometres along corridor")
    ax.set_title("Maintenance jobs placed on real sections", fontsize=10)
    ax.legend(fontsize=8, ncol=3)
    save(fig, "03_jobs_on_network.png")

    # 4 demand by department and activity
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ac = Counter((j["dept"], j["activity"]) for j in jobs)
    labels = [f"{a}" for (d, a) in sorted(ac, key=lambda k: (k[0], -ac[k]))]
    vals = [ac[k] for k in sorted(ac, key=lambda k: (k[0], -ac[k]))]
    cols = [col[k[0]] for k in sorted(ac, key=lambda k: (k[0], -ac[k]))]
    ax.barh(range(len(vals)), vals, color=cols)
    ax.set_yticks(range(len(vals)))
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis(); ax.set_xlabel("jobs")
    ax.set_title("Maintenance demand by activity (Poisson from periodicity)", fontsize=10)
    ax.grid(alpha=.25, axis="x")
    save(fig, "04_demand_by_activity.png")

    # 5 duration distribution
    fig, ax = plt.subplots(figsize=(7, 3.2))
    for d, c in col.items():
        v = [j["duration_mean_min"] for j in jobs if j["dept"] == d]
        if v:
            ax.hist(v, bins=24, alpha=.6, color=c, label=d)
    ax.set_xlabel("planned duration (min)"); ax.set_ylabel("jobs")
    ax.set_title("Job duration distribution", fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=.25, axis="y")
    save(fig, "05_duration_distribution.png")

    # 6 block demand heatmap: section-line x preferred day
    fig, ax = plt.subplots(figsize=(7, 4.5))
    H = ds["meta"]["horizon_days"]
    sids = sorted({j["section_id"] for j in jobs})
    idx = {s: i for i, s in enumerate(sids)}
    M = np.zeros((len(sids), H + 1))
    for br in ds["block_requests"]:
        j = next((x for x in jobs if x["job_id"] == br["job_id"]), None)
        if j and j["section_id"] in idx:
            M[idx[j["section_id"]], min(H, max(0, br["preferred_date"]))] += 1
    im = ax.imshow(M, aspect="auto", cmap="YlOrBr")
    ax.set_yticks(range(len(sids)))
    ax.set_yticklabels(sids, fontsize=5.5)
    ax.set_xlabel("preferred day"); ax.set_title("Block demand heatmap", fontsize=10)
    fig.colorbar(im, ax=ax, label="requests")
    save(fig, "06_block_demand_heatmap.png")

    # 7 occupancy timeline for the busiest section-line
    per = Counter(m["from_code"] + "-" + m["to_code"] + "-" + m["direction"] for m in mov)
    if per:
        key = max(per, key=per.get)
        fig, ax = plt.subplots(figsize=(7, 2.6))
        for m in mov:
            k = m["from_code"] + "-" + m["to_code"] + "-" + m["direction"]
            if k != key:
                continue
            ax.vlines(m["enter_min"] / 60, 0, 1,
                      color="#9A6B00" if m["is_synthetic"] else "#15616D", lw=1.1)
        ax.set_xlim(0, 24); ax.set_yticks([])
        ax.set_xlabel("hour"); ax.set_title(f"Occupancy timeline — {key}", fontsize=10)
        save(fig, "07_occupancy_timeline.png")

    return made


def write(ds, outdir, figdir):
    os.makedirs(outdir, exist_ok=True)
    s = stats(ds)
    with open(os.path.join(outdir, "quality_report.json"), "w") as f:
        json.dump(s, f, indent=2)
    lines = ["# Dataset quality report", ""]
    for k, v in s.items():
        lines.append(f"- **{k}**: {v}")
    with open(os.path.join(outdir, "quality_report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return s
