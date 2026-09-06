"""Automated dataset validation.

Every check returns (name, passed, detail). A dataset that fails a CRITICAL
check is not shippable; WARN checks are reported and allowed. The scaffold
source mode fails a critical check by design, so a placeholder build can never
be mistaken for a real one.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

CRITICAL, WARN = "CRITICAL", "WARN"


def _c(name, ok, detail, level=CRITICAL):
    return {"check": name, "level": level, "passed": bool(ok), "detail": detail}


def validate(ds) -> list[dict]:
    r = []
    st, sec, jobs = ds["stations"], ds["sections"], ds["jobs"]
    mov, stops = ds["movements"], ds["train_stops"]
    acts = {a["id"]: a for a in ds["activities"]["activities"]}

    # ------------------------------------------------------------- source
    r.append(_c("source_mode_is_real", ds["meta"]["source_mode"] == "datameet",
                f"source_mode={ds['meta']['source_mode']}; a scaffold build is for "
                f"development only and must not be presented"))

    # ------------------------------------------------------------ network
    bad = [s for s in st if not (6 < s["latitude"] < 38 and 68 < s["longitude"] < 98)]
    r.append(_c("station_coordinates_in_india", not bad,
                f"{len(bad)} station(s) outside India bounds"
                + (f": {[b['station_code'] for b in bad[:3]]}" if bad else "")))
    codes = [s["station_code"] for s in st]
    r.append(_c("station_codes_unique", len(codes) == len(set(codes)),
                f"{len(codes)} stations, {len(set(codes))} unique"))
    r.append(_c("positive_section_lengths", all(s["length_km"] > 0 for s in sec),
                f"min length {min((s['length_km'] for s in sec), default=0):.3f} km"))
    seqs = sorted(s["seq"] for s in st)
    r.append(_c("corridor_is_a_path", seqs == list(range(len(st))),
                f"station sequence {'contiguous' if seqs == list(range(len(st))) else 'BROKEN'}"))
    # every consecutive station pair must have at least one section-line
    pairs = {(s["from_station_code"], s["to_station_code"]) for s in sec}
    order = [s["station_code"] for s in sorted(st, key=lambda x: x["seq"])]
    missing = [(a, b) for a, b in zip(order, order[1:]) if (a, b) not in pairs]
    r.append(_c("network_connected", not missing,
                f"{len(missing)} consecutive pair(s) with no section-line"))
    unsupported = [s for s in sec if s["support_trains"] < 1]
    r.append(_c("sections_supported_by_real_trains", not unsupported,
                f"{len(unsupported)} section(s) not traversed by any real train", WARN))

    # ---------------------------------------------------------- timetable
    # Times are minutes-of-day, so a stop that spans midnight legitimately has
    # departure < arrival. Compare modulo the day and bound the dwell instead.
    MAX_DWELL_MIN = 120

    def _num(v):
        """Minutes-of-day as a number, or None if absent.

        Real timetables legitimately omit the arrival at an originating station
        and the departure at a terminating one, so this must tolerate a missing
        value however it was loaded: None in memory, '' after a CSV round-trip.
        Checking the type rather than `is not None` keeps the check correct
        under both, which is what the generator and the standalone validator
        need in order to agree.
        """
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        if isinstance(v, str) and v.strip() != "":
            try:
                return float(v)
            except ValueError:
                return None
        return None

    checked = [(a, d) for a, d in
               ((_num(s["arrival_min"]), _num(s["departure_min"])) for s in stops)
               if a is not None and d is not None]
    bad_t = [(a, d) for a, d in checked
             if not (0 <= (d - a) % 1440 <= MAX_DWELL_MIN)]
    r.append(_c("arrival_before_departure", not bad_t,
                f"{len(bad_t)} stop(s) with an implausible dwell out of "
                f"{len(checked)} with both times "
                f"(allowing for midnight crossing, max {MAX_DWELL_MIN} min)"))
    per_train = defaultdict(list)
    for s in stops:
        per_train[s["train_number"]].append(s["stop_seq"])
    broken = [t for t, v in per_train.items() if sorted(v) != list(range(min(v), min(v) + len(v)))]
    r.append(_c("train_routes_contiguous", not broken,
                f"{len(broken)} train(s) with a non-contiguous stop sequence", WARN))
    real_mov = [m for m in mov if not m["is_synthetic"]]
    n_days = max(1, ds["meta"]["horizon_days"])
    per_line = Counter(m["from_code"] + m["to_code"] for m in real_mov)
    busiest = max(per_line.values()) if per_line else 0
    r.append(_c("plausible_daily_train_count", 5 <= busiest <= 400,
                f"busiest station pair sees {busiest} real train movements/day",
                WARN))
    headways = [s["headway_min"] for s in sec]
    r.append(_c("plausible_headways", all(3 <= h <= 60 for h in headways),
                f"headway range {min(headways)}-{max(headways)} min"))

    # Trains whose published name we cannot read are weighted by a fallback, and
    # a fallback that nobody declared is a silent modelling choice. Two separate
    # obligations, so two separate checks: the weight must exist, and the share
    # of traffic riding on it must stay small enough to be honest about.
    A = ds.get("assumptions") or {}
    tw = ((A.get("traffic") or {}).get("train_weight") or {})
    r.append(_c("unknown_class_fallback_weight_declared", "UNKNOWN" in tw,
                f"assumptions.yaml traffic.train_weight "
                f"{'declares' if 'UNKNOWN' in tw else 'does NOT declare'} an "
                f"explicit UNKNOWN weight"
                + (f" (={tw.get('UNKNOWN')})" if "UNKNOWN" in tw else "")))
    unk = [m for m in mov if str(m.get("train_class", "")).upper() == "UNKNOWN"]
    share = len(unk) / len(mov) if mov else 0.0
    r.append(_c("train_class_unknown_share", share <= 0.05,
                f"{len(unk)}/{len(mov)} movements ({share:.1%}) have an "
                f"unreadable service class and use the declared fallback weight",
                WARN))

    # The dataset declares its track attributes rather than corroborating them
    # against OSM. That is an acceptable prototype position, but it must be
    # stated in the data, not left for a reader to infer.
    srcs = Counter(s.get("track_source", "") for s in sec)
    r.append(_c("track_source_labelled",
                set(srcs) <= {"osm", "declared"} and "" not in srcs,
                f"track_source per section-line: "
                f"{', '.join(f'{k}={v}' for k, v in sorted(srcs.items()))}"
                f" (declared = from config/corridor.yaml, NOT corroborated "
                f"against OpenStreetMap)"))

    # -------------------------------------------------------- maintenance
    secids = {s["section_id"] for s in sec}
    seclen = {s["section_id"]: s["length_km"] for s in sec}
    orphan = [j for j in jobs if j["section_id"] not in secids]
    r.append(_c("jobs_on_real_sections", not orphan,
                f"{len(orphan)} job(s) reference a section that does not exist"))
    oob = [j for j in jobs if not (0 <= j["km_from"] < j["km_to"] <= seclen.get(j["section_id"], 0) + 1e-6)]
    r.append(_c("job_footprint_inside_section", not oob,
                f"{len(oob)} job(s) with a footprint outside the section"))
    mismatch = [j for j in jobs if j["activity"] in acts and
                acts[j["activity"]]["dept"] != j["dept"]]
    r.append(_c("dept_matches_activity", not mismatch,
                f"{len(mismatch)} job(s) whose department contradicts the activity catalogue"))
    protbad = []
    for j in jobs:
        a = acts.get(j["activity"])
        if not a:
            continue
        p = a["protection"]
        if (int(bool(p["T"])), int(bool(p["P"])), int(bool(p["D"]))) != \
           (j["needs_T"], j["needs_P"], j["needs_D"]):
            protbad.append(j["job_id"])
    r.append(_c("protection_matches_catalogue", not protbad,
                f"{len(protbad)} job(s) whose protection differs from the catalogue"))
    durbad = [j for j in jobs if not (j["duration_min_min"] <= j["duration_mean_min"]
                                      <= j["duration_max_min"] and j["duration_sd_min"] > 0)]
    r.append(_c("durations_plausible", not durbad,
                f"{len(durbad)} job(s) with an implausible duration triple"))
    # a job must be able to fit its own minimum block
    toolong = [j for j in jobs if j["duration_mean_min"] > max(ds["block_lengths"])]
    r.append(_c("jobs_fit_some_block", not toolong,
                f"{len(toolong)} job(s) longer than the largest permitted block "
                f"({max(ds['block_lengths'])} min) - these SHOULD be deferred with "
                f"an explanation, not silently dropped", WARN))
    resbad = [j for j in jobs if "_" not in (j["resources"] or "")]
    r.append(_c("resources_well_formed", not resbad,
                f"{len(resbad)} job(s) with a malformed resource id"))

    # ----------------------------------------------------------- bundling
    classd = [j for j in jobs if j["needs_train_movements"] or j["needs_live_ohe"]]
    r.append(_c("class_d_jobs_present", len(classd) > 0,
                f"{len(classd)} job(s) requiring the negation of a block; a dataset "
                f"without these lets a broken compatibility engine look correct", WARN))
    contradictory = [j for j in jobs if j["needs_live_ohe"] and j["needs_P"]]
    r.append(_c("no_self_contradictory_jobs", not contradictory,
                f"{len(contradictory)} job(s) needing live OHE AND a power block"))
    pr = ds["pairing_rules"]
    known = set(acts)
    badpair = [p for p in pr if p["activity"] not in known]
    r.append(_c("pairing_rules_reference_real_activities", not badpair,
                f"{len(badpair)} pairing rule(s) naming an unknown activity"))
    cited = [p for p in pr if p.get("source")]
    r.append(_c("pairing_rules_all_cited", len(cited) == len(pr),
                f"{len(cited)}/{len(pr)} pairing rules carry a source citation"))

    # ---------------------------------------------------------- scenarios
    sc = ds["scenarios"]
    r.append(_c("scenarios_defined", len(sc) >= 5, f"{len(sc)} scenarios"))
    def _f(v, default=1.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default
    r.append(_c("scenario_multipliers_sane",
                all(0.1 <= _f(s.get("demand_scale", 1)) <= 5 for s in sc),
                "demand scales within 0.1-5x"))

    # --------------------------------------------------------- provenance
    from . import provenance
    miss = provenance.assert_complete("jobs", list(jobs[0].keys())) if jobs else []
    r.append(_c("provenance_registered_for_jobs", not miss,
                f"unregistered job columns: {miss}" if miss else "all job columns registered"))
    return r


def summarise(results) -> tuple[bool, str]:
    crit = [r for r in results if r["level"] == CRITICAL and not r["passed"]]
    warn = [r for r in results if r["level"] == WARN and not r["passed"]]
    ok = not crit
    return ok, f"{len(results)} checks, {len(crit)} critical failure(s), {len(warn)} warning(s)"
