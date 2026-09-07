"""Whether plans are written anywhere, and where.

A plan is the one thing this system produces that the frozen CSVs cannot hold.
Until now it lived in a dict and died with the process: restart the server and
every plan id a controller had been given became a 404. These tables are the
first thing in this project that genuinely needs a database.

    BLOCKPLAN_PERSIST_PLANS=0    keep plans in memory only   (DEFAULT)
    BLOCKPLAN_PERSIST_PLANS=1    also write them to PostgreSQL

OFF BY DEFAULT, and separate from BLOCKPLAN_DATA_SOURCE. The two answer
different questions -- where inputs are read from, and whether outputs are
kept -- and either combination is meaningful: reading the frozen CSVs while
persisting plans is the obvious way to run this today, since snapshot 1 IS the
frozen dataset. Startup must not require PostgreSQL, so the default writes
nothing and imports nothing.

Turning it on with no database configured raises rather than quietly falling
back to memory. Someone who asks for persistence and silently does not get it
finds out at the worst possible moment.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from . import paths

ENV_VAR = "BLOCKPLAN_PERSIST_PLANS"

#: The frozen dataset is loaded as snapshot 1 by blockplan_db.loader, from
#: exactly the files paths.FROZEN_TREE names. So a plan computed from the
#: frozen tree can be attributed to snapshot 1 truthfully -- but only that
#: tree; see snapshot_id_for().
FROZEN_SNAPSHOT_ID = 1


class PersistenceError(RuntimeError):
    """Plans cannot be persisted as asked, and pretending otherwise is worse."""


@dataclass(frozen=True)
class RawPlanValues:
    """The unrounded figures behind a response, for storage.

    The API response rounds -- objective and the costs to 1 dp, reliability to
    3 -- so it cannot be the source of what gets written: rounding is not
    reversible, and the block fingerprint test_reference_plan.py pins is taken
    over repr() of the RAW reliability. These come from PlanInternals, which
    holds the solver's own objects, and are carried alongside the payload so
    the store never has to reach into planner internals itself.

    `blocks` maps block_id -> (reliability, traffic_cost, exp_overrun_cost).
    """

    objective: float
    blocks: Mapping[str, tuple[float, float, float]]


@runtime_checkable
class PlanStore(Protocol):
    """Somewhere plans and approvals are kept."""

    @property
    def enabled(self) -> bool:
        """False for the in-memory default. Nothing else need be true of it."""

    def describe(self) -> str:
        """One line for /health."""

    def save_plan(self, payload: Mapping[str, Any], *, snapshot_id: int,
                  raw: RawPlanValues) -> None:
        """Write a plan, replacing any earlier one with the same id."""

    def load_plan(self, plan_id: str, *, snapshot_id: int) -> dict[str, Any] | None:
        """One plan, shaped exactly as POST /plan returned it, or None."""

    def recent_plans(self, limit: int, *,
                     snapshot_id: int) -> list[dict[str, Any]]:
        """The most recently created plans for this snapshot, newest first."""

    def plan_ids(self, *, snapshot_id: int) -> tuple[str, ...]:
        """Every persisted plan id for this snapshot."""

    def record_approval(self, plan_id: str, block_id: str, decision: str,
                        *, snapshot_id: int, decided_by: str | None = None,
                        note: str | None = None) -> None:
        """Append a controller's decision on one block."""

    def approvals_for(self, plan_id: str, *,
                      snapshot_id: int) -> list[dict[str, Any]]:
        """Every decision recorded against a plan, oldest first."""


class NullPlanStore:
    """The default: plans stay in memory and die with the process.

    Every method is a no-op or empty rather than an error, so the service can
    call the store unconditionally and has no `if self._store is not None`
    scattered through it.
    """

    enabled = False

    def describe(self) -> str:
        return "in memory only (not persisted)"

    def save_plan(self, payload: Mapping[str, Any], *, snapshot_id: int,
                  raw: RawPlanValues) -> None:
        return None

    def load_plan(self, plan_id: str, *, snapshot_id: int) -> dict[str, Any] | None:
        return None

    def recent_plans(self, limit: int, *,
                     snapshot_id: int) -> list[dict[str, Any]]:
        return []

    def plan_ids(self, *, snapshot_id: int) -> tuple[str, ...]:
        return ()

    def record_approval(self, plan_id: str, block_id: str, decision: str,
                        *, snapshot_id: int, decided_by: str | None = None,
                        note: str | None = None) -> None:
        return None

    def approvals_for(self, plan_id: str, *,
                      snapshot_id: int) -> list[dict[str, Any]]:
        return []

    def __repr__(self) -> str:
        return "NullPlanStore()"


def snapshot_id_for(context: Any) -> int:
    """Which snapshot a plan built from this context belongs to.

    Every persisted plan records the data it was produced from, so that an
    approved plan stays reproducible against exactly those rows.

    A plan is identified by (snapshot_id, plan_id), not by plan_id alone -- see
    the note above the plans table in schema.sql -- so this answer is part of
    the plan's identity, not just a label attached to it.

    Two cases, and the second is the one that needs justifying:

      * A context built from the database knows its own snapshot id. Use it.
      * A context built from the FROZEN tree is attributed to snapshot 1,
        because blockplan_db.loader defines snapshot 1 as exactly those files
        and Phase 3 measured the round trip as identical. This is a claim about
        provenance, so it is made only for the frozen tree itself.

    Any other tree -- a temporary directory, a copy, an experiment -- raises.
    Attributing those to snapshot 1 would put a false provenance record in the
    audit trail, which is worse than refusing to store the plan.
    """
    declared = getattr(context, "snapshot_id", None)
    if declared is not None:
        return int(declared)
    if context.tree == paths.FROZEN_TREE:
        return FROZEN_SNAPSHOT_ID
    raise PersistenceError(
        f"cannot attribute a dataset snapshot to the tree at {context.tree.root}. "
        "Plans are persisted with the snapshot they were computed from, and "
        "this tree is neither the frozen dataset nor a database snapshot.")


def resolve(env: Mapping[str, str] | None = None) -> PlanStore:
    """Pick a plan store from the environment. In-memory unless asked."""
    env = os.environ if env is None else env
    raw = env.get(ENV_VAR, "0").strip().lower()

    if raw in ("", "0", "false", "no", "off"):
        return NullPlanStore()
    if raw not in ("1", "true", "yes", "on"):
        raise PersistenceError(
            f"{ENV_VAR}={raw!r} is not a yes/no value. Use 1 or 0.")

    from blockplan_db.connection import is_configured

    if not is_configured(env):
        raise PersistenceError(
            f"{ENV_VAR} is on but no database is configured. Set "
            "BLOCKPLAN_DATABASE_URL, or the PG* variables, or turn it off.")

    from blockplan_db.plan_store import PostgresPlanStore

    return PostgresPlanStore()
