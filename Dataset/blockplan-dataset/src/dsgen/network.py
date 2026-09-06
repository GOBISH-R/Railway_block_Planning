"""Build the corridor network from real public data.

The corridor is not asserted, it is *discovered*: we name two real endpoint
station codes, then let the real train schedules tell us which stations lie
between them and in what order. A station enters the network only if enough
distinct real trains support it. That means the topology is a consequence of
published data rather than a claim we make about the railway, and it is exactly
reproducible from the source files plus this code.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
import re
from dataclasses import dataclass, field


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    R = 6371.0088
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def hhmmss_to_min(s) -> int | None:
    if not s or not isinstance(s, str):
        return None
    parts = s.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


@dataclass
class Station:
    code: str
    name: str
    lat: float
    lon: float
    zone: str
    state: str
    seq: int = -1
    is_junction: bool = False


@dataclass
class SectionLine:
    section_id: str
    from_code: str
    to_code: str
    line: str
    length_km: float
    tracks: int
    electrified: bool
    headway_min: int
    degraded_factor: float
    support_trains: int
    track_source: str            # "osm" | "declared"


@dataclass
class Corridor:
    stations: list
    sections: list
    trains: dict = field(default_factory=dict)      # number -> meta
    stops: list = field(default_factory=list)       # flat stop rows
    movements: list = field(default_factory=list)   # section traversals
    published_distance_km: float | None = None
    scale_factor: float = 1.0


def _station_index(features) -> dict:
    out = {}
    for f in features:
        p = f.get("properties", f)
        code = (p.get("code") or "").strip()
        if not code:
            continue
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        if lat is None or lon is None:
            continue
        out[code] = Station(code=code, name=p.get("name", ""), lat=float(lat),
                            lon=float(lon), zone=p.get("zone", "") or "",
                            state=p.get("state", "") or "")
    return out


def _trains_from_schedules(schedules) -> dict:
    by_train = defaultdict(list)
    for r in schedules:
        p = r.get("properties", r)
        num = str(p.get("train_number", "")).strip()
        code = (p.get("station_code") or "").strip()
        if not num or not code:
            continue
        by_train[num].append({
            "train_number": num,
            "train_name": p.get("train_name", ""),
            "station_code": code,
            "arrival_min": hhmmss_to_min(p.get("arrival")),
            "departure_min": hhmmss_to_min(p.get("departure")),
            "day": int(p.get("day") or 1),
        })
    # DataMeet schedules are already in stop order per train; keep that order
    # and only use time to break genuine ties.
    return dict(by_train)


def classify_train(name: str, type_hint: str | None) -> str:
    """Service class from the operator's own published train name.

    Substring matching on the fully spelled words alone left a quarter of the
    corridor's trains UNKNOWN, because the published names abbreviate: "SF Exp",
    "SF Special", "Expres", "InterCity". Those abbreviations are part of the
    source string, not an inference we are adding, so matching them is reading
    the data rather than guessing at it. The rules below are applied to
    whitespace/punctuation-delimited TOKENS, in a fixed order, so the result is
    deterministic and reproducible:

      1. named premium services (Vande Bharat, Rajdhani, Shatabdi, Duronto);
      2. the token SF, or the word SUPERFAST                 -> SUPERFAST;
      3. the tokens EXP / EXPS / EXPRES / EXPRESS, or INTERCITY -> EXPRESS;
      4. MEMU / DEMU / PASSENGER / MAIL as written;
      5. anything still unmatched stays UNKNOWN. We do NOT fall back to a
         numbering-range heuristic: a name we cannot read is reported as
         unreadable, and the UNKNOWN share is a published validation metric with
         an explicit fallback weight in assumptions.yaml.

    SUPERFAST is tested before EXPRESS because "SF Exp" is a superfast service:
    the SF qualifier is the specific one.
    """
    n = (name or "").upper()
    t = (type_hint or "").upper()
    tokens = set(re.split(r"[^A-Z0-9]+", n)) - {""}

    for key, cls in (("VANDE BHARAT", "VANDE_BHARAT"), ("RAJDHANI", "RAJDHANI"),
                     ("SHATABDI", "SHATABDI"), ("DURONTO", "SUPERFAST"),
                     ("SUPERFAST", "SUPERFAST")):
        if key in n:
            return cls
    if "SF" in tokens:
        return "SUPERFAST"
    for key, cls in (("MEMU", "MEMU"), ("DEMU", "DEMU"),
                     ("PASSENGER", "PASSENGER"), ("EXPRESS", "EXPRESS"),
                     ("MAIL", "MAIL")):
        if key in n:
            return cls
    if tokens & {"EXP", "EXPS", "EXPRES", "EXPRESSS"} or "INTERCITY" in n:
        return "EXPRESS"

    for key, cls in (("EXP", "EXPRESS"), ("SUF", "SUPERFAST"), ("PASS", "PASSENGER"),
                     ("MEMU", "MEMU"), ("MAIL", "MAIL")):
        if key in t:
            return cls
    return "UNKNOWN"


def build_corridor(raw, cfg, osm=None) -> Corridor:
    sa = cfg["study_area"]
    a, b = sa["endpoints"]["from_station_code"], sa["endpoints"]["to_station_code"]
    via = list(sa.get("via_station_codes") or [])
    min_support = int(sa.get("min_supporting_trains", 3))

    stations = _station_index(raw.stations)
    by_train = _trains_from_schedules(raw.schedules)
    train_meta = {}
    for f in raw.trains:
        p = f.get("properties", f)
        num = str(p.get("number", "")).strip()
        if num:
            train_meta[num] = p

    # ---- 1. find real trains that traverse the corridor, in either direction
    candidates = []
    for num, stops in by_train.items():
        codes = [s["station_code"] for s in stops]
        if a not in codes or b not in codes:
            continue
        ia, ib = codes.index(a), codes.index(b)
        lo, hi = (ia, ib) if ia < ib else (ib, ia)
        seg = codes[lo:hi + 1]
        if via and not all(v in seg for v in via):
            continue
        candidates.append((num, stops[lo:hi + 1], ia < ib))
    if not candidates:
        raise SystemExit(
            f"No real train in the source traverses {a} .. {b}"
            + (f" via {via}" if via else "")
            + ". Check the endpoint codes against stations.json.")

    # ---- 2. the fullest stopping pattern gives the candidate station order
    #         (the slowest passenger train stops nearly everywhere)
    _, longest, longest_down = max(candidates, key=lambda c: len(c[1]))
    order = [s["station_code"] for s in longest]
    if not longest_down:
        order = list(reversed(order))

    # ---- 3. keep only stations supported by enough distinct real trains
    seen = Counter()
    for _, seg, _ in candidates:
        for s in {x["station_code"] for x in seg}:
            seen[s] += 1
    kept = [c for c in order if seen[c] >= min_support and c in stations]
    if a in stations and a not in kept:
        kept.insert(0, a)
    if b in stations and b not in kept:
        kept.append(b)
    if len(kept) < 3:
        raise SystemExit(f"Corridor collapsed to {len(kept)} stations; "
                         f"lower min_supporting_trains.")

    corridor_stations = []
    for i, c in enumerate(kept):
        st = stations[c]
        st.seq = i
        st.is_junction = "JUNCTION" in st.name.upper() or " JN" in st.name.upper()
        corridor_stations.append(st)
    pos = {s.code: s.seq for s in corridor_stations}

    # ---- 4. section lengths: haversine, then scaled to the published route
    #         distance if the source gives one for a corridor train
    raw_len = []
    for i in range(len(corridor_stations) - 1):
        p, q = corridor_stations[i], corridor_stations[i + 1]
        raw_len.append(haversine_km(p.lat, p.lon, q.lat, q.lon))
    total_hav = sum(raw_len)

    published = None
    for num, _, _ in candidates:
        m = train_meta.get(num) or {}
        d = m.get("distance")
        fc, tc = m.get("from_station_code"), m.get("to_station_code")
        if d and fc in pos and tc in pos:
            span = abs(pos[fc] - pos[tc])
            if span >= len(corridor_stations) - 2:
                published = float(d)
                break
    scale = (published / total_hav) if (published and total_hav > 0) else 1.0
    # a chord is always shorter than the track; a scale below 1 means the
    # published distance covers a different span, so ignore it
    if not (1.0 <= scale <= 1.6):
        scale, published = 1.0, None

    # ---- 5. track configuration
    tc_cfg = cfg["track_configuration"]
    fb = tc_cfg["fallback"]
    osm_tracks = _osm_track_lookup(osm) if osm else None

    sections = []
    support = Counter()
    for _, seg, _ in candidates:
        codes = [x["station_code"] for x in seg if x["station_code"] in pos]
        for u, v in zip(codes, codes[1:]):
            support[tuple(sorted((u, v)))] += 1

    for i in range(len(corridor_stations) - 1):
        p, q = corridor_stations[i], corridor_stations[i + 1]
        length = round(raw_len[i] * scale, 3)
        tracks, electrified, src = fb["tracks"], fb["electrified"], "declared"
        if osm_tracks:
            hit = _nearest_osm(osm_tracks, p, q)
            if hit:
                tracks, electrified, src = hit[0], hit[1], "osm"
        labels = (cfg["line_labels"]["double"] if tracks >= 2
                  else cfg["line_labels"]["single"])
        for lab in labels:
            sections.append(SectionLine(
                section_id=f"{p.code}-{q.code}-{lab}",
                from_code=p.code, to_code=q.code, line=lab,
                length_km=length, tracks=tracks, electrified=electrified,
                headway_min=0, degraded_factor=0.0,
                support_trains=support[tuple(sorted((p.code, q.code)))],
                track_source=src))

    cor = Corridor(stations=corridor_stations, sections=sections,
                   published_distance_km=published, scale_factor=scale)

    # ---- 6. real train stops and section movements
    for num, seg, down in candidates:
        meta = train_meta.get(num) or {}
        name = seg[0]["train_name"]
        cor.trains[num] = {
            "train_number": num, "train_name": name,
            "train_class": classify_train(name, meta.get("type")),
            "is_synthetic": False,
            "direction": "DN" if down else "UP",
        }
        prev = None
        for k, s in enumerate(seg):
            if s["station_code"] not in pos:
                continue
            cor.stops.append({**s, "stop_seq": k})
            if prev is not None:
                cor.movements.extend(_movement(prev, s, pos, cor.trains[num], corridor_stations))
            prev = s
    return cor


def _movement(prev, cur, pos, tmeta, stations):
    """One traversal of one section-line by one real train."""
    u, v = prev["station_code"], cur["station_code"]
    if u not in pos or v not in pos:
        return []
    lo, hi = (u, v) if pos[u] < pos[v] else (v, u)
    direction = "DN" if pos[u] < pos[v] else "UP"
    t = prev["departure_min"] if prev["departure_min"] is not None else prev["arrival_min"]
    if t is None:
        return []
    return [{
        "train_number": tmeta["train_number"],
        "train_class": tmeta["train_class"],
        "from_code": lo, "to_code": hi,
        "direction": direction,
        "enter_min": int(t),
        "is_synthetic": False,
    }]


def assign_headways(cor: Corridor, assumptions) -> None:
    """Derive a service headway per section-line from the REAL timetable.

    5th percentile of observed gaps between consecutive movements. Where too
    few real movements are observed the configured default is used and the row
    is provenance E rather than B.
    """
    import numpy as np
    tr = assumptions["traffic"]
    by_line = {}
    for m in cor.movements:
        for s in cor.sections:
            if s.from_code == m["from_code"] and s.to_code == m["to_code"]:
                if s.tracks >= 2 and s.line != m["direction"]:
                    continue
                by_line.setdefault(s.section_id, []).append(m["enter_min"])
    for s in cor.sections:
        times = sorted(by_line.get(s.section_id, []))
        default = (tr["single_line_headway_min"] if s.tracks < 2
                   else tr["default_headway_min"])
        if len(times) >= 8:
            gaps = np.diff(times)
            gaps = gaps[gaps > 0]
            # The 5th percentile of observed gaps is evidence of how CLOSE
            # together trains have actually been run, which lower-bounds the
            # line's capability. It cannot be evidence that the line is
            # incapable of a tighter headway: a quiet section simply has large
            # gaps. So the observation may only tighten the configured default,
            # never loosen it.
            obs = int(round(np.percentile(gaps, 5))) if len(gaps) else default
            h = int(min(default, max(4, obs)))
        else:
            h = default
        s.headway_min = h
        s.degraded_factor = float(tr["degraded_factor"]) if s.tracks >= 2 else 1.0


def _osm_track_lookup(osm):
    out = []
    for el in osm.get("elements", []):
        tags = el.get("tags") or {}
        geom = el.get("geometry") or []
        if not geom:
            continue
        try:
            tracks = int(tags.get("tracks", 0)) or None
        except ValueError:
            tracks = None
        elec = tags.get("electrified", "") not in ("", "no")
        if tracks is None and "electrified" not in tags:
            continue
        out.append((tracks, elec, [(g["lat"], g["lon"]) for g in geom]))
    return out or None


def _nearest_osm(osm_tracks, p, q, max_km=1.5):
    mid_lat, mid_lon = (p.lat + q.lat) / 2, (p.lon + q.lon) / 2
    best, best_d = None, max_km
    for tracks, elec, geom in osm_tracks:
        for (la, lo) in geom[::4]:
            d = haversine_km(mid_lat, mid_lon, la, lo)
            if d < best_d:
                best_d, best = d, (tracks, elec)
    if best and best[0]:
        return best
    return None
