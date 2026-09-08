"""A TMS/SMMS/TDMS feed as a planning data source.

    BLOCKPLAN_DATA_SOURCE=feed
    BLOCKPLAN_FEED_DIR=<directory holding the three JSON feeds>
    BLOCKPLAN_FEED_URL=<base URL of the three endpoints>     (either, not both)

The third `DataSource`, after the frozen CSVs and PostgreSQL. It materialises a
dataset tree and hands it back, exactly as blockplan_db/repository.py does, so
the frozen blockplan_adapter loaders remain the only code that ever parses a
job, reusing the frozen loaders. That pattern was measured in Phase 3 of the database
track as reproducing the reference plan byte for byte; reusing it means this
path is verifiable the same way, and blockplan_ingest/verify.py does exactly
that.

WHAT THE FEED REPLACES, AND WHAT IT DOES NOT.

It replaces the JOBS. Sections, stations, movements and pairing rules come from
the frozen tree unchanged: those are infrastructure, the working timetable, and
departmental rules. A maintenance-management system raises work; it does not
publish the WTT or the ACTM. Sourcing them from a feed would be inventing an
interface that does not exist.

SCENARIOS BECOME TRAFFIC CONDITIONS. The frozen dataset generates a different
job set per scenario, because each scenario models different demand. A live
feed does not: there is one real backlog. So the feed's jobs are written as the
job set for EVERY scenario, and what still varies between them is the traffic --
freight weighting, extra passenger paths, withdrawn windows. The question
changes from "what if demand were higher" to "how does today's actual backlog
plan under peak traffic", which is the question a division would ask.

This is a real semantic difference from the frozen dataset and it is stated
here rather than left to be inferred from behaviour.
"""
from __future__ import annotations

import csv
import os
import shutil
import tempfile
from typing import Any, Mapping, Sequence

from blockplan_service import paths

from . import feeds
from .contract import ContractError, FeedValidation

FEED = "feed"
FEED_DIR_ENV = "BLOCKPLAN_FEED_DIR"
FEED_URL_ENV = "BLOCKPLAN_FEED_URL"

#: Reference tables copied from the frozen tree. A feed supplies none of these.
_REFERENCE_FILES = (
    ("processed", "sections.csv"),
    ("processed", "stations.csv"),
    ("processed", "movements.csv"),
    ("processed", "pairing_rules.csv"),
    ("processed", "activities.csv"),
    ("processed", "resources.csv"),
)


class FeedDataSourceError(RuntimeError):
    """The feed cannot be used as a planning source."""


def materialise(feed_dir: str | None, destination: str, *,
                reference: paths.DatasetTree | None = None,
                required: bool = True,
                base_url: str | None = None
                ) -> tuple[paths.DatasetTree, FeedValidation]:
    """Build a dataset tree from a feed directory plus the frozen reference.

    Returns the tree and the validation result, because the caller must be able
    to see what was rejected. A feed that silently dropped a third of its work
    orders and produced a smaller, tidier plan would look like a success.
    """
    reference = reference or paths.FROZEN_TREE
    tree = paths.DatasetTree(destination)
    for directory in (tree.processed_dir, tree.scenarios_dir, tree.scenario_jobs_dir):
        os.makedirs(directory, exist_ok=True)

    for subdir, name in _REFERENCE_FILES:
        source = os.path.join(reference.root, subdir, name)
        if not os.path.isfile(source):
            raise FeedDataSourceError(f"reference file missing: {source}")
        shutil.copy(source, os.path.join(tree.root, subdir, name))
    shutil.copy(reference.scenarios_csv, tree.scenarios_csv)

    known_sections = [row["section_id"] for row in _rows(tree.sections_csv)]
    known_activities = [row["activity_id"] for row in
                        _rows(os.path.join(tree.processed_dir, "activities.csv"))]

    origin = base_url or feed_dir
    source_feeds = (feeds.fetch_all(base_url, required=required) if base_url
                    else feeds.read_all(feed_dir, required=required))
    validation = feeds.validate_feeds(
        source_feeds, known_sections=known_sections,
        known_activities=known_activities)
    if not validation.accepted:
        raise FeedDataSourceError(
            f"{origin}: no usable work orders "
            f"({len(validation.rejected)} rejected)")

    try:
        job_rows = feeds.to_job_rows(validation.accepted, tree)
    except ContractError as exc:
        raise FeedDataSourceError(str(exc)) from exc

    _write_jobs(os.path.join(tree.processed_dir, "jobs.csv"), job_rows)
    for row in _rows(tree.scenarios_csv):
        _write_jobs(tree.scenario_jobs_csv(row["scenario"]), job_rows)

    missing = tree.missing()
    if missing:
        raise FeedDataSourceError(f"materialised tree is incomplete: {missing}")
    return tree, validation


def _rows(path: str) -> list[dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_jobs(path: str, rows: Sequence[Mapping[str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(feeds.JOB_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


class FeedDataSource:
    """One live demand set, ingested and materialised at startup."""

    name = FEED
    snapshot_id = None

    def __init__(self, feed_dir: str | None = None, *, required: bool = True,
                 base_url: str | None = None) -> None:
        if bool(feed_dir) == bool(base_url):
            raise FeedDataSourceError(
                "give exactly one of BLOCKPLAN_FEED_DIR or BLOCKPLAN_FEED_URL. "
                "With both set it is not clear which backlog was planned, and "
                "that is the one thing a plan must never be vague about.")
        self.feed_dir = feed_dir
        self.base_url = base_url
        self.required = required
        self._tree: paths.DatasetTree | None = None
        self._workspace: tempfile.TemporaryDirectory | None = None
        self.validation: FeedValidation | None = None

    def open(self) -> paths.DatasetTree:
        if self._tree is not None:
            return self._tree
        if self.feed_dir and not os.path.isdir(self.feed_dir):
            raise FeedDataSourceError(f"no feed directory at {self.feed_dir}")

        self._workspace = tempfile.TemporaryDirectory(prefix="blockplan-feed-")
        self._tree, self.validation = materialise(
            self.feed_dir, self._workspace.name, required=self.required,
            base_url=self.base_url)
        return self._tree

    @property
    def origin(self) -> str:
        return self.base_url or self.feed_dir or "<unset>"

    def close(self) -> None:
        if self._workspace is not None:
            self._workspace.cleanup()
            self._workspace = None
            self._tree = None

    def describe(self) -> str:
        if self.validation is None:
            return f"TMS/SMMS/TDMS feed at {self.origin} (not yet read)"
        return f"TMS/SMMS/TDMS feed at {self.origin}: {self.validation.summary()}"

    def __repr__(self) -> str:
        return f"FeedDataSource({self.origin!r})"


def from_env(env: Mapping[str, str]) -> FeedDataSource:
    directory = env.get(FEED_DIR_ENV, "").strip()
    url = env.get(FEED_URL_ENV, "").strip()
    if not directory and not url:
        raise FeedDataSourceError(
            f"BLOCKPLAN_DATA_SOURCE=feed needs {FEED_DIR_ENV} or {FEED_URL_ENV} "
            "to say where the TMS/SMMS/TDMS work orders are. Nothing is "
            "guessed: planning from the wrong backlog is worse than not "
            "starting.")
    return FeedDataSource(directory or None, base_url=url or None)
