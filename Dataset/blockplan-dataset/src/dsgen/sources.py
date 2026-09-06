"""Raw source acquisition.

Two modes:

  datameet   download the real public data, hash it, cache it. This is what
             you run for anything you intend to show or publish.

  scaffold   build a clearly-labelled placeholder topology so the pipeline can
             be developed and tested without network access. Station
             identifiers are deliberately of the form SCAFFOLD-nn so that no
             output can ever be mistaken for real railway geography, and the
             validator refuses to certify a scaffold dataset.

Nothing in scaffold mode may be presented to anyone. That is enforced, not
merely requested: every artefact carries `source_mode` and validate_dataset.py
exits non-zero on a scaffold build unless --allow-scaffold is passed.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass

RAW_URLS = {
    # DataMeet / Indian Railways, CC0 public domain dedication.
    # Repository: https://github.com/datameet/railways
    "stations.json": "https://raw.githubusercontent.com/datameet/railways/master/stations.json",
    "trains.json": "https://raw.githubusercontent.com/datameet/railways/master/trains.json",
    "schedules.json": "https://raw.githubusercontent.com/datameet/railways/master/schedules.json",
}

OVERPASS = "https://overpass-api.de/api/interpreter"

# Overpass QL to pull railway line geometry and tags for a bounding box.
# Returns railway=rail ways with the tags we care about: tracks, electrified,
# voltage, gauge, usage. OpenStreetMap data, ODbL licence.
OVERPASS_QUERY = """
[out:json][timeout:120];
(
  way["railway"="rail"]({bbox});
);
out tags geom;
"""


@dataclass
class RawBundle:
    mode: str                     # "datameet" | "scaffold"
    stations: list                # GeoJSON features or scaffold dicts
    schedules: list
    trains: list
    hashes: dict


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def fetch_datameet(raw_dir: str) -> RawBundle:
    """Download (or reuse) the three DataMeet files and record their hashes."""
    os.makedirs(raw_dir, exist_ok=True)
    payloads, hashes = {}, {}
    for name, url in RAW_URLS.items():
        path = os.path.join(raw_dir, name)
        if not os.path.exists(path):
            print(f"  downloading {name} from {url}")
            with urllib.request.urlopen(url, timeout=180) as r, open(path, "wb") as f:
                f.write(r.read())
        with open(path, "rb") as f:
            b = f.read()
        hashes[name] = _sha256(b)
        payloads[name] = json.loads(b)
        print(f"  {name:16s} sha256[:16]={hashes[name]}  {len(b)/1e6:.1f} MB")

    st = payloads["stations.json"]
    tr = payloads["trains.json"]
    sc = payloads["schedules.json"]
    return RawBundle(
        mode="datameet",
        stations=st["features"] if isinstance(st, dict) else st,
        trains=tr["features"] if isinstance(tr, dict) else tr,
        schedules=sc["features"] if isinstance(sc, dict) else sc,
        hashes=hashes,
    )


def build_scaffold(n_stations: int = 12, n_trains: int = 40, seed: int = 42) -> RawBundle:
    """A placeholder network with unmistakably synthetic identifiers.

    Shaped like the real thing so every downstream stage exercises the same
    code path, but no station code, name or coordinate here corresponds to
    anything real, and it is labelled so at every level.
    """
    import numpy as np
    rng = np.random.default_rng(seed)

    stations = []
    lat, lon = 12.50, 78.50           # arbitrary start point, NOT a real station
    for i in range(n_stations):
        lat += 0.055 + rng.normal(0, 0.006)
        lon -= 0.075 + rng.normal(0, 0.008)
        stations.append({
            "properties": {
                "code": f"SCAFFOLD-{i:02d}",
                "name": f"Scaffold Placeholder {i:02d}",
                "zone": "SCAFFOLD",
                "state": "SCAFFOLD",
            },
            "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        })

    classes = ["EXPRESS"] * 18 + ["PASSENGER"] * 10 + ["MEMU"] * 8 + ["SUPERFAST"] * 4
    schedules, trains = [], []
    for t in range(n_trains):
        klass = classes[t % len(classes)]
        down = t % 2 == 0
        order = range(n_stations) if down else range(n_stations - 1, -1, -1)
        # slower classes stop everywhere, faster ones skip
        skip = {"SUPERFAST": 3, "EXPRESS": 2, "PASSENGER": 1, "MEMU": 1}[klass]
        start = int(rng.integers(0, 24 * 60))
        clock = start
        seq = [i for k, i in enumerate(order) if k % skip == 0 or k in (0, n_stations - 1)]
        num = f"9{t:04d}"
        for k, i in enumerate(seq):
            clock += int(rng.integers(12, 26))
            arr = clock
            dep = clock + (2 if k not in (0, len(seq) - 1) else 0)
            clock = dep
            schedules.append({
                "train_number": num,
                "train_name": f"SCAFFOLD {klass} {t:02d}",
                "station_code": stations[i]["properties"]["code"],
                "station_name": stations[i]["properties"]["name"],
                "arrival": f"{(arr//60)%24:02d}:{arr%60:02d}:00",
                "departure": f"{(dep//60)%24:02d}:{dep%60:02d}:00",
                "day": 1 + arr // 1440,
                "id": f"{num}-{k}",
            })
        trains.append({"properties": {
            "number": num, "name": f"SCAFFOLD {klass} {t:02d}", "type": klass,
            "distance": None,
            "from_station_code": stations[seq[0]]["properties"]["code"],
            "to_station_code": stations[seq[-1]]["properties"]["code"],
        }})

    return RawBundle(mode="scaffold", stations=stations, schedules=schedules,
                     trains=trains, hashes={"scaffold": f"seed{seed}"})


def fetch_osm_tracks(bbox: tuple[float, float, float, float], cache: str) -> dict | None:
    """Pull railway line tags from OpenStreetMap via Overpass. ODbL licence.

    bbox is (south, west, north, east). Returns None if unavailable, in which
    case the caller falls back to the declared configuration and flags the rows.
    """
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    q = OVERPASS_QUERY.format(bbox=",".join(f"{v:.4f}" for v in bbox))
    try:
        req = urllib.request.Request(OVERPASS, data=q.encode(),
                                     headers={"User-Agent": "blockplan-dataset/1.0"})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read())
        with open(cache, "w") as f:
            json.dump(data, f)
        return data
    except Exception as e:                       # noqa: BLE001
        print(f"  OSM unavailable ({e.__class__.__name__}); "
              f"falling back to declared track configuration")
        return None
