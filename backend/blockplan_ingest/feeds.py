"""Reading a TMS / SMMS / TDMS feed, and turning it into planner input.

Three feeds, one per source system, merged into the single demand set the
planner works from. Each feed is JSON on disk here; a real integration replaces
`read_records` with an HTTP call and changes nothing else, because everything
downstream consumes `MaintenanceDemand` objects rather than the wire format.

WHY THIS PRODUCES CSV ROWS RATHER THAN core.Job OBJECTS.

The blockplan_adapter loaders must be reused verbatim, and
those loaders take file paths. One of them, load_trains, derives each train's id
from its ROW POSITION in the file -- so a reimplementation that built domain
objects directly would have to reproduce that, and any drift would change the
plan silently.

So a feed materialises a dataset tree, exactly as the PostgreSQL reader already
does (blockplan_db/repository.py). The pattern is proven: Phase 3 of the
database track measured a materialised tree as reproducing the reference plan
byte for byte. Reusing it here means the feed path is verified the same way,
and the frozen loaders stay the only thing that ever parses a job.

WHAT A FEED CANNOT SUPPLY. Corridor geography (sections, stations) and the
train timetable (movements) are infrastructure and working-timetable data, not
maintenance demand. TMS/SMMS/TDMS raise work; they do not publish the WTT. So a
feed replaces the JOBS and nothing else, and the reference tables come from the
frozen dataset. Pretending a maintenance system could supply the timetable
would be the same fabrication as inventing its schema.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from blockplan_service import paths

from .contract import (
    DEPARTMENT_OF,
    SOURCE_SYSTEMS,
    SYSTEM_OF,
    ContractError,
    FeedValidation,
    MaintenanceDemand,
    validate,
)

#: Filename each source system publishes into a feed directory.
FEED_FILES = {system: f"{system.lower()}_work_orders.json"
              for system in SOURCE_SYSTEMS}

#: jobs.csv's columns, in file order. The materialised tree must match the
#: frozen layout exactly or the adapter's DictReader sees different keys.
JOB_COLUMNS = (
    "job_id", "dept", "activity", "section_id", "location_desc",
    "km_from", "km_to", "needs_T", "needs_P", "needs_D",
    "needs_train_movements", "needs_live_ohe",
    "duration_mean_min", "duration_sd_min", "duration_min_min", "duration_max_min",
    "min_block_min", "resources", "due_day", "criticality",
    "priority", "uncertainty_level", "provenance",
)

PROVENANCE = "F:ingested_from_maintenance_management_system"


class FeedError(RuntimeError):
    """A feed cannot be read or is unusable as a whole."""


@dataclass(frozen=True)
class Feed:
    """One source system's published work orders."""

    source_system: str
    records: tuple[Mapping[str, Any], ...]
    origin: str

    @property
    def dept(self) -> str:
        return DEPARTMENT_OF[self.source_system]


def read_feed(directory: str, source_system: str) -> Feed:
    """Read one system's JSON file from a feed directory.

    A real integration swaps this for an HTTP GET. Everything after it works on
    records, so the change stops here.
    """
    if source_system not in SOURCE_SYSTEMS:
        raise FeedError(f"{source_system!r} is not one of {', '.join(SOURCE_SYSTEMS)}")

    path = os.path.join(directory, FEED_FILES[source_system])
    if not os.path.isfile(path):
        raise FeedError(f"no {source_system} feed at {path}")

    with open(path, encoding="utf-8") as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as exc:
            raise FeedError(f"{path}: not valid JSON ({exc})") from exc

    records = payload.get("work_orders") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise FeedError(
            f"{path}: expected a list of work orders, or an object with a "
            f"'work_orders' list; got {type(records).__name__}")

    # The file says which system it is from, but the filename already did. A
    # record that disagrees is a routing mistake worth catching here.
    stamped = []
    for record in records:
        row = dict(record)
        declared = str(row.get("source_system", source_system)).strip().upper()
        if declared != source_system:
            raise FeedError(
                f"{path}: work order {row.get('work_order_id')!r} declares "
                f"source_system={declared!r} in the {source_system} feed")
        row["source_system"] = source_system
        stamped.append(row)

    return Feed(source_system, tuple(stamped), path)


def fetch_feed(base_url: str, source_system: str, *, timeout: float = 10.0) -> Feed:
    """Pull one system's work orders over HTTP.

    The only difference from read_feed is where the bytes come from -- the
    contract, the validation and the mapping are identical, which is the point
    of keeping the wire format out of everything downstream.

    urllib rather than requests: this must not add a dependency to a project
    whose packaged app is required to run with nothing installed beyond its
    pinned requirements.
    """
    import urllib.error
    import urllib.request

    url = f"{base_url.rstrip('/')}/{source_system.lower()}/work-orders"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise FeedError(f"{url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise FeedError(f"{url}: response is not valid JSON ({exc})") from exc

    records = payload.get("work_orders") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise FeedError(f"{url}: expected a list of work orders")

    stamped = []
    for record in records:
        row = dict(record)
        row["source_system"] = source_system
        stamped.append(row)
    return Feed(source_system, tuple(stamped), url)


def fetch_all(base_url: str, *, systems: Sequence[str] = SOURCE_SYSTEMS,
              required: bool = True, timeout: float = 10.0) -> tuple[Feed, ...]:
    """Every system's work orders from one base URL."""
    fetched = []
    for system in systems:
        try:
            fetched.append(fetch_feed(base_url, system, timeout=timeout))
        except FeedError:
            if required:
                raise
    if not fetched:
        raise FeedError(f"no usable feeds at {base_url}")
    return tuple(fetched)


def read_all(directory: str, *, systems: Sequence[str] = SOURCE_SYSTEMS,
             required: bool = True) -> tuple[Feed, ...]:
    """Every system's feed from one directory.

    `required=False` tolerates a missing system -- a division that has not
    connected SMMS yet still gets a plan from TMS and TDMS, and the absence is
    visible in the result rather than assumed away.
    """
    feeds = []
    for system in systems:
        try:
            feeds.append(read_feed(directory, system))
        except FeedError:
            if required:
                raise
    if not feeds:
        raise FeedError(f"no usable feeds in {directory}")
    return tuple(feeds)


def validate_feeds(feeds: Iterable[Feed], *,
                   known_sections: Sequence[str] | None = None,
                   known_activities: Sequence[str] | None = None) -> FeedValidation:
    """All systems' records, validated together.

    Together rather than one at a time, because a duplicate work order id
    across two systems is exactly the collision that would otherwise appear as
    a mysteriously overwritten job.
    """
    records: list[Mapping[str, Any]] = []
    for feed in feeds:
        records.extend(feed.records)
    return validate(records, known_sections=known_sections,
                    known_activities=known_activities)


# -- demand -> the frozen job-row shape --------------------------------------

def _catalogue(tree: paths.DatasetTree | None = None) -> dict[str, dict[str, str]]:
    """activity_id -> its catalogue row.

    The protection regime, the minimum block and the resource class are
    properties of the ACTIVITY, not of the work order. A feed says "tamp this
    stretch"; whether tamping needs a power block is a rule, and it lives in the
    catalogue. Taking it from the feed instead would let a source system
    silently change a protection requirement.
    """
    directory = tree.processed_dir if tree is not None else paths.PROCESSED_DIR
    with open(os.path.join(directory, "activities.csv"), encoding="utf-8") as f:
        return {row["activity_id"]: row for row in csv.DictReader(f)}


def _duration_bounds() -> dict[str, tuple[float, float]]:
    """activity_id -> (min, max) truncation bounds, from the frozen config.

    activities.csv does not carry them -- it has the mean and sd but not the
    bounds -- so this reads config/activities.yaml, which is where the
    generator itself takes them from (dsgen/demand.py:153).
    """
    import yaml

    path = os.path.join(paths.CONFIG_DIR, "activities.yaml")
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    out = {}
    for activity in config.get("activities", []):
        duration = activity.get("duration_min") or {}
        if "min" in duration and "max" in duration:
            out[activity["id"]] = (float(duration["min"]), float(duration["max"]))
    return out


def _section_labels(tree: paths.DatasetTree | None = None) -> dict[str, str]:
    path = tree.sections_csv if tree is not None else paths.SECTIONS_CSV
    with open(path, encoding="utf-8") as f:
        return {row["section_id"]: f"{row['from_station_code']}-"
                                   f"{row['to_station_code']} {row['line']}"
                for row in csv.DictReader(f)}


def to_job_rows(demands: Sequence[MaintenanceDemand],
                tree: paths.DatasetTree | None = None) -> list[dict[str, str]]:
    """Work orders -> rows in jobs.csv's exact shape.

    The feed supplies WHAT and WHERE and WHEN. The catalogue supplies the
    protection regime and the block minimum. Neither source is asked for what
    the other owns.

    duration_min_min and duration_max_min are NOT requested from the feed and
    NOT derived from the mean and sd. They are the truncation bounds of the
    lognormal core.py samples for reliability, they are per-activity constants,
    and they live in the frozen config at
    config/activities.yaml -> duration_min.{min,max}.

    Deriving them instead was tried and is wrong: mean +/- 3 sigma gave 6 and
    50.4 minutes where the catalogue says 18 and 65 for the same activity.
    Wrong bounds mean a differently truncated distribution, a different
    reliability, and a different plan -- which the round-trip gate would have
    caught, but only after the mistake was already in the adapter.
    """
    catalogue = _catalogue(tree)
    labels = _section_labels(tree)
    bounds = _duration_bounds()

    rows = []
    for demand in demands:
        activity = catalogue.get(demand.activity_code)
        if activity is None:
            raise ContractError(
                f"{demand.work_order_id}: activity {demand.activity_code!r} is "
                "not in the catalogue, so its protection regime is unknown")

        low, high = bounds.get(demand.activity_code, (None, None))
        if low is None:
            raise ContractError(
                f"{demand.work_order_id}: activity {demand.activity_code!r} has "
                "no duration bounds in config/activities.yaml, so the "
                "reliability model has nothing to truncate against")
        where = labels.get(demand.section_id, demand.section_id)
        rows.append({
            "job_id": demand.work_order_id,
            "dept": demand.dept,
            "activity": demand.activity_code,
            "section_id": demand.section_id,
            "location_desc": f"{where} km {demand.km_from:.2f}",
            "km_from": f"{demand.km_from:.3f}",
            "km_to": f"{demand.km_to:.3f}",
            # Rules, from the catalogue -- never from the feed.
            "needs_T": activity["needs_T"],
            "needs_P": activity["needs_P"],
            "needs_D": activity["needs_D"],
            "needs_train_movements": activity["needs_train_movements"],
            "needs_live_ohe": activity["needs_live_ohe"],
            "duration_mean_min": _trim(demand.duration_mean_min),
            "duration_sd_min": _trim(demand.duration_sd_min),
            "duration_min_min": _trim(low),
            "duration_max_min": _trim(high),
            "min_block_min": activity["min_block_min"],
            # The allocated machine or gang if the feed named one. The
            # fallback shares one instance across the class, which core.py
            # reads as "these jobs cannot run together" -- pessimistic, not
            # neutral. See MaintenanceDemand.resource_id.
            "resources": demand.resource_id or f"{activity['resource_class']}_0",
            "due_day": str(int(demand.due_day)),
            "criticality": _trim(demand.criticality),
            # UI labels. The dataset's own documentation is explicit that the
            # optimiser must not consume these, so they are derived for display
            # and nothing reads them back into the model.
            "priority": _priority(demand),
            "uncertainty_level": _uncertainty(demand),
            "provenance": f"{PROVENANCE}:{demand.source_system}",
        })
    return rows


def _trim(value: float) -> str:
    """Render a float the way the frozen CSVs do: no trailing zeros beyond need."""
    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _priority(demand: MaintenanceDemand) -> str:
    if demand.due_day <= 0 or demand.criticality >= 2.0:
        return "URGENT"
    return "HIGH" if demand.criticality >= 1.4 else "NORMAL"


def _uncertainty(demand: MaintenanceDemand) -> str:
    if demand.duration_mean_min <= 0:
        return "MEDIUM"
    ratio = demand.duration_sd_min / demand.duration_mean_min
    return "HIGH" if ratio > 0.28 else ("LOW" if ratio < 0.15 else "MEDIUM")


def demand_to_feed_records(job_rows: Iterable[Mapping[str, str]]
                           ) -> list[dict[str, Any]]:
    """The inverse: existing job rows -> feed records.

    This is what makes the round-trip gate possible. Export the frozen dataset
    into feed format, ingest it back, and the planner must return the reference
    plan -- the same proof the PostgreSQL reader passes. Without an inverse the
    adapter could only be tested against data invented to suit it.
    """
    out = []
    for row in job_rows:
        out.append({
            "work_order_id": row["job_id"],
            "source_system": SYSTEM_OF[row["dept"]],
            "activity_code": row["activity"],
            "section_id": row["section_id"],
            "km_from": float(row["km_from"]),
            "km_to": float(row["km_to"]),
            "due_day": int(row["due_day"]),
            "criticality": float(row["criticality"]),
            "duration_mean_min": float(row["duration_mean_min"]),
            "duration_sd_min": float(row["duration_sd_min"]),
            "resource_id": row.get("resources") or None,
        })
    return out


def write_feed_directory(records: Sequence[Mapping[str, Any]], destination: str
                         ) -> dict[str, str]:
    """Split records by source system and write one JSON file per system."""
    os.makedirs(destination, exist_ok=True)
    written = {}
    for system in SOURCE_SYSTEMS:
        mine = [r for r in records
                if str(r.get("source_system", "")).upper() == system]
        path = os.path.join(destination, FEED_FILES[system])
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"source_system": system, "work_orders": mine}, f, indent=1)
        written[system] = path
    return written
