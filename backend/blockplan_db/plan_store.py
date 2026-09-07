"""Plans, blocks, deferred jobs and approvals, in PostgreSQL.

The write half of the output side. A plan goes in as the API returned it and
comes back out shaped identically -- that is the contract this module is judged
by, and tests/test_plan_persistence.py asserts it as literal dict equality
against a live response rather than field by field.

Two things it does NOT do.

It does not persist PlanInternals. Explaining a block needs the jobs, bundles,
16,746 columns and 11,648 windows behind a plan, which is far too much to write
per plan. So a restored plan behaves exactly like one whose internals have been
evicted in a long-running process, which is a case that already existed and is
already handled: a Why request against it answers 409 "re-run the plan to
explain it", and re-POSTing the same request falls through planner.py's cache
check, recomputes the internals under the SAME plan id, and the Why request
then succeeds. Verified end to end, in separate processes, in
tests/test_plan_persistence.py.

It does not round. plans.objective and the three plan_blocks costs hold the raw
values the solver produced; the rounding the response shows is applied on read,
using planner.py's own constants rather than a second copy of the rule. Storing
the rounded value would make the raw one unrecoverable and would quietly break
the block fingerprint that tests/test_reference_plan.py pins.

IDENTITY IS (snapshot_id, plan_id). plan_id is the request hash, so the same
request against a different snapshot yields the same id and a different plan.
Every method here therefore takes the snapshot explicitly rather than defaulting
to one -- a plan cannot be read, written or approved without saying which data
it belongs to. See the note above the plans table in schema.sql for what went
wrong when plan_id alone was the key. Which snapshot a context belongs to, and
when that question can be answered honestly at all, is decided in
blockplan_service/persistence.py.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from blockplan_service.persistence import RawPlanValues
from blockplan_service.planner import COST_DP, OBJECTIVE_DP, RELIABILITY_DP

#: Restored into memory at startup, newest first. Bounded because _plans is
#: unbounded and a long-lived deployment would otherwise reload every plan it
#: has ever produced; anything older is still reachable, one at a time, through
#: load_plan().
DEFAULT_RESTORE_LIMIT = 100

_PLAN_COLUMNS = (
    "snapshot_id", "plan_id", "scenario", "theta", "horizon_days",
    "max_bundle_size", "mc_samples", "seed", "status", "objective",
    "summary", "instance", "stage_timings_s",
)

_BLOCK_COLUMNS = (
    "snapshot_id", "plan_id", "block_id", "section_id", "day", "start_min",
    "end_min", "length", "reliability", "traffic_cost", "exp_overrun_cost",
    "dept_mix", "job_ids",
)


class PostgresPlanStore:
    """A connection per operation, opened on demand.

    Not a pool. Saving happens once per solve -- a ~13 s operation -- and
    reading happens on a cache miss, so connection setup is nowhere near the
    cost that would justify one. A pool would also have to be shared with the
    planning lock's threading model, which is a real design question and not
    one this phase needs to answer.
    """

    enabled = True

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = None if env is None else dict(env)

    def _connect(self):
        from .connection import connect

        return connect(self._env)

    def describe(self) -> str:
        from .connection import database_url

        return f"persisted to {database_url(self._env)}"

    def __repr__(self) -> str:
        return "PostgresPlanStore()"

    # -- writing -----------------------------------------------------------

    def save_plan(self, payload: Mapping[str, Any], *, snapshot_id: int,
                  raw: RawPlanValues) -> None:
        """Write one plan and its blocks and deferred jobs, as one transaction.

        Replaces any existing plan with the same id. That is not an edge case:
        the plan id is the request hash, so re-solving the same request is the
        normal way to arrive here twice, and it produces the same plan. Deleting
        first lets plan_blocks and plan_deferred cascade rather than needing
        per-row upserts.
        """
        plan_id = payload["plan_id"]
        instance = payload["instance"]

        plan_row = (
            snapshot_id,
            plan_id,
            payload["scenario"],
            float(payload["theta"]),
            int(payload["horizon_days"]),
            int(instance["max_bundle_size"]),
            int(instance["mc_samples"]),
            instance["seed"],
            payload["status"],
            float(raw.objective),      # raw, not the response's rounded figure
            json.dumps(payload["summary"]),
            json.dumps(dict(instance)),
            json.dumps(payload["stage_timings_s"]),
        )

        block_rows = []
        for b in payload["blocks"]:
            reliability, traffic_cost, exp_overrun = raw.blocks[b["block_id"]]
            block_rows.append(
                (snapshot_id, plan_id, b["block_id"], b["section_id"], int(b["day"]),
                 int(b["start_min"]), int(b["end_min"]), int(b["length"]),
                 float(reliability), float(traffic_cost), float(exp_overrun),
                 list(b["dept_mix"]), list(b["job_ids"])))
        deferred_rows = [
            (snapshot_id, plan_id, seq, d["job_id"], d["dept"])
            for seq, d in enumerate(payload["deferred"], start=1)
        ]

        with self._connect() as conn:
            with conn.cursor() as cur:
                # Scoped by BOTH: deleting on plan_id alone would destroy the
                # same request's plan under every other snapshot.
                cur.execute("DELETE FROM plans WHERE snapshot_id = %s AND "
                            "plan_id = %s", (snapshot_id, plan_id))
                cur.execute(
                    f"INSERT INTO plans ({', '.join(_PLAN_COLUMNS)}) VALUES "
                    f"({', '.join(['%s'] * len(_PLAN_COLUMNS))})", plan_row)
                if block_rows:
                    cur.executemany(
                        f"INSERT INTO plan_blocks ({', '.join(_BLOCK_COLUMNS)}) "
                        f"VALUES ({', '.join(['%s'] * len(_BLOCK_COLUMNS))})",
                        block_rows)
                if deferred_rows:
                    cur.executemany(
                        "INSERT INTO plan_deferred (snapshot_id, plan_id, seq, "
                        "job_id, dept) VALUES (%s, %s, %s, %s, %s)", deferred_rows)
            conn.commit()

    def record_approval(self, plan_id: str, block_id: str, decision: str,
                        *, snapshot_id: int, decided_by: str | None = None,
                        note: str | None = None) -> None:
        """Append a decision. Append, not update: the table is an audit trail,
        and a controller reversing an earlier call is itself a fact worth
        keeping."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO approvals (snapshot_id, plan_id, block_id, decision, "
                "decided_by, note) VALUES (%s, %s, %s, %s, %s, %s)",
                (snapshot_id, plan_id, block_id, decision, decided_by, note))
            conn.commit()

    # -- reading -----------------------------------------------------------

    def load_plan(self, plan_id: str, *, snapshot_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {', '.join(_PLAN_COLUMNS)} FROM plans "
                "WHERE snapshot_id = %s AND plan_id = %s",
                (snapshot_id, plan_id)).fetchone()
            if row is None:
                return None
            return self._assemble(conn, row)

    def recent_plans(self, limit: int = DEFAULT_RESTORE_LIMIT, *,
                     snapshot_id: int) -> list[dict[str, Any]]:
        """Newest first, and only this snapshot's.

        Restoring another snapshot's plans into a process serving this one would
        put plans in memory that were computed from data it is not reading.
        """
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(_PLAN_COLUMNS)} FROM plans "
                "WHERE snapshot_id = %s ORDER BY created_at DESC, plan_id "
                "LIMIT %s", (snapshot_id, limit)).fetchall()
            return [self._assemble(conn, row) for row in rows]

    def plan_ids(self, *, snapshot_id: int) -> tuple[str, ...]:
        with self._connect() as conn:
            return tuple(r[0] for r in conn.execute(
                "SELECT plan_id FROM plans WHERE snapshot_id = %s ORDER BY plan_id",
                (snapshot_id,)).fetchall())

    def approvals_for(self, plan_id: str, *,
                      snapshot_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT block_id, decision, decided_by, decided_at, note "
                "FROM approvals WHERE snapshot_id = %s AND plan_id = %s "
                "ORDER BY decided_at, block_id", (snapshot_id, plan_id)).fetchall()
        return [
            {"block_id": b, "decision": d, "decided_by": by,
             "decided_at": at, "note": note}
            for b, d, by, at, note in rows
        ]

    def snapshots_holding(self, plan_id: str) -> tuple[int, ...]:
        """Every snapshot this request has been planned against.

        Plural by design: the same request planned against two snapshots is two
        plans sharing one id, which is exactly what the composite key allows.
        """
        with self._connect() as conn:
            return tuple(r[0] for r in conn.execute(
                "SELECT snapshot_id FROM plans WHERE plan_id = %s "
                "ORDER BY snapshot_id", (plan_id,)).fetchall())

    # -- rebuilding the response -------------------------------------------

    def _assemble(self, conn, row) -> dict[str, Any]:
        """Rebuild the POST /plan response from its rows.

        Rounding is applied here, from the raw stored values, using planner.py's
        constants. Block order comes from block_id, which is safe because
        block_id_map() numbers blocks B0001.. in solve order and zero-pads them,
        so lexicographic order is the original order. Deferred jobs have no such
        id, which is why plan_deferred carries seq.
        """
        (snapshot_id, plan_id, scenario, theta, horizon_days,
         _max_bundle, _mc, _seed, status, objective,
         summary, instance, timings) = row

        blocks = [
            {
                "block_id": b_id,
                "section_id": section_id,
                "day": day,
                "start_min": start_min,
                "length": length,
                "end_min": end_min,
                "reliability": round(reliability, RELIABILITY_DP),
                "traffic_cost": round(traffic_cost, COST_DP),
                "exp_overrun_cost": round(exp_overrun, COST_DP),
                "dept_mix": list(dept_mix),
                "job_ids": list(job_ids),
            }
            for (b_id, section_id, day, start_min, end_min, length, reliability,
                 traffic_cost, exp_overrun, dept_mix, job_ids) in conn.execute(
                "SELECT block_id, section_id, day, start_min, end_min, length, "
                "reliability, traffic_cost, exp_overrun_cost, dept_mix, job_ids "
                "FROM plan_blocks WHERE snapshot_id = %s AND plan_id = %s "
                "ORDER BY block_id", (snapshot_id, plan_id)).fetchall()
        ]

        deferred = [
            {"job_id": job_id, "dept": dept}
            for job_id, dept in conn.execute(
                "SELECT job_id, dept FROM plan_deferred WHERE snapshot_id = %s "
                "AND plan_id = %s ORDER BY seq", (snapshot_id, plan_id)).fetchall()
        ]

        return {
            "plan_id": plan_id,
            "scenario": scenario,
            "horizon_days": horizon_days,
            "theta": theta,
            # False, as shape_plan_response produced it. plan()'s cache path is
            # what sets this to True, and it does so on its own copy; a stored
            # plan must not claim to have been served from cache when it was
            # read from disk.
            "cache_hit": False,
            "status": status,
            "objective": round(objective, OBJECTIVE_DP),
            "blocks": blocks,
            "deferred": deferred,
            "summary": summary,
            "stage_timings_s": timings,
            "instance": instance,
        }
