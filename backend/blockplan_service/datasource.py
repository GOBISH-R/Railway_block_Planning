"""Where the planning inputs come from: the frozen CSVs, or PostgreSQL.

One decision, made once at startup, and everything downstream is unaware of it.
A data source hands over a `DatasetTree`; the adapter loaders read that tree and
cannot tell which source produced it. That is the whole abstraction.

    BLOCKPLAN_DATA_SOURCE=csv        the frozen dataset (DEFAULT)
    BLOCKPLAN_DATA_SOURCE=postgres   snapshot 1 out of the database
    BLOCKPLAN_DATA_SOURCE=feed       a TMS/SMMS/TDMS feed (BLOCKPLAN_FEED_DIR)

CSV IS THE DEFAULT, AND DELIBERATELY SO. Every number this project publishes was
produced from the frozen tree, the demo has to run with no database installed,
and `python run.py` must keep working on a laptop that has never seen
PostgreSQL. The database path is opt-in until there is a reason for it to be
otherwise -- and today there is not, because snapshot 1 IS the frozen dataset.
It becomes worth switching when snapshots 2, 3, ... hold live extracts.

The two sources are interchangeable and that is measured, not asserted:
tests/test_datasource.py builds a PlanningContext from each and compares them,
and tests/test_db_verify.py plans from both and compares the resulting blocks.
"""
from __future__ import annotations

import os
import tempfile
from typing import Mapping, Protocol, runtime_checkable

from . import paths

CSV = "csv"
POSTGRES = "postgres"
FEED = "feed"

ENV_VAR = "BLOCKPLAN_DATA_SOURCE"
SNAPSHOT_ENV_VAR = "BLOCKPLAN_SNAPSHOT_ID"


class DataSourceError(RuntimeError):
    """The requested source cannot be used, and guessing would be worse."""


@runtime_checkable
class DataSource(Protocol):
    """Somewhere a dataset tree can be obtained from."""

    @property
    def name(self) -> str:
        """Short identifier: "csv", "postgres"."""

    @property
    def snapshot_id(self) -> int | None:
        """The snapshot this represents, or None for the frozen files."""

    def open(self) -> paths.DatasetTree:
        """Make the tree available and return it. Called once, at startup."""

    def describe(self) -> str:
        """One line for /health and for a startup log."""


class CsvDataSource:
    """The frozen dataset, read where it lies.

    Opens nothing, copies nothing, writes nothing. This is the path every
    published figure came from.
    """

    name = CSV
    snapshot_id = None

    def open(self) -> paths.DatasetTree:
        tree = paths.FROZEN_TREE
        missing = tree.missing()
        if missing:
            raise DataSourceError(f"the frozen dataset is incomplete: {missing}")
        return tree

    def describe(self) -> str:
        return f"frozen CSVs at {paths.DATASET_DIR}"

    def __repr__(self) -> str:
        return "CsvDataSource()"


class DatabaseDataSource:
    """One snapshot out of PostgreSQL, materialised to a temporary tree.

    The materialisation is what lets the adapter loaders be reused verbatim;
    see blockplan_db/repository.py for why that matters and what it costs. It
    happens once, at startup, and the directory lives as long as the process.

    Importing blockplan_db is deferred to open() so that a backend with no
    psycopg installed still imports this module -- CSV mode must not depend on
    the database being available in any sense.
    """

    name = POSTGRES

    def __init__(self, snapshot_id: int = 1) -> None:
        self._snapshot_id = snapshot_id
        self._tree: paths.DatasetTree | None = None
        self._workspace: tempfile.TemporaryDirectory | None = None
        self._info_line = f"snapshot {snapshot_id}"

    @property
    def snapshot_id(self) -> int:
        return self._snapshot_id

    def open(self) -> paths.DatasetTree:
        if self._tree is not None:
            return self._tree

        from blockplan_db import repository
        from blockplan_db.connection import connect, database_url

        self._workspace = tempfile.TemporaryDirectory(prefix="blockplan-snapshot-")
        with connect() as conn:
            info = repository.read_snapshot_info(conn, self._snapshot_id)
            self._tree = repository.materialise(
                conn, self._workspace.name, snapshot_id=self._snapshot_id)
        self._info_line = f"{info.describe()} from {database_url()}"
        return self._tree

    def close(self) -> None:
        """Drop the materialised tree. Not called in normal operation -- the
        process holds it for its lifetime -- but tests create sources freely."""
        if self._workspace is not None:
            self._workspace.cleanup()
            self._workspace = None
            self._tree = None

    def describe(self) -> str:
        return self._info_line

    def __repr__(self) -> str:
        return f"DatabaseDataSource(snapshot_id={self._snapshot_id})"


def resolve(env: Mapping[str, str] | None = None) -> DataSource:
    """Pick a source from the environment. CSV unless told otherwise.

    An unrecognised value raises rather than falling back to CSV: someone who
    sets BLOCKPLAN_DATA_SOURCE=postgresql (or misspells it) wants the database,
    and quietly serving them the frozen CSVs instead would look like it worked.
    """
    env = os.environ if env is None else env
    name = env.get(ENV_VAR, CSV).strip().lower()

    if name in ("", CSV):
        return CsvDataSource()
    if name == POSTGRES:
        raw = env.get(SNAPSHOT_ENV_VAR, "1")
        try:
            snapshot_id = int(raw)
        except ValueError:
            raise DataSourceError(
                f"{SNAPSHOT_ENV_VAR}={raw!r} is not an integer") from None
        return DatabaseDataSource(snapshot_id)
    if name == FEED:
        # Imported here, not at module scope: blockplan_ingest must not be on
        # the default path, for the same reason blockplan_db is not.
        from blockplan_ingest.datasource import from_env

        return from_env(env)

    raise DataSourceError(
        f"{ENV_VAR}={name!r} is not a data source. Use {CSV!r} (the default, "
        f"the frozen dataset), {POSTGRES!r}, or {FEED!r}.")
