"""The planning service: the lock, the caches, the pipeline, the DTOs.

THE LOCK IS THE POINT OF THIS MODULE.

core.py holds mutable module-level state, and the adapter configures the
optimiser by monkey-patching module globals (THETA, KAPPA, LAMBDA_CLOSE,
CLOSING, TRAIN_WEIGHT, MAX_SPAN_KM, ALLOWED_BLOCK_LENGTHS, MANDATORY_PAIRING)
plus one shared core.RNG. That is entirely fine for a script: one process, one
configuration, one run, top to bottom.

It is not fine behind FastAPI, which runs a synchronous endpoint in a
threadpool. Two users pressing Re-plan with different theta values within a few
seconds of each other would interleave -- one request sets theta=0.85, the
other 0.95, and both solve against whichever won the race. Worse, both draw
from the same core.RNG, which destroys the determinism that was deliberately
engineered into the core, and produces a bug that cannot be reproduced on
demand.

The agreed fix is this single module-level lock covering the ENTIRE sequence:
acquire -> reset RNG -> apply config -> apply overrides -> run pipeline ->
shape results -> release. Refactoring core.py to thread parameters through
function signatures was considered and explicitly rejected: it breaks the
freeze and invalidates the verified benchmark numbers.

Serialising costs nothing that matters. One plan takes ~4.5 s warm and this
system will never have more than a handful of concurrent users. Correctness and
reproducibility are worth far more here than concurrency.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from . import paths
from .context import PlanningContext
from .persistence import NullPlanStore, PlanStore, RawPlanValues, snapshot_id_for
from .windows import DEFAULT_KEEP_PER_DAY, WindowCache

paths.ensure_import_paths()

import core  # noqa: E402

# Benchmark-matching defaults. These are the settings that produced the frozen
# artefacts; they are defaults for convenience, never silently substituted for
# a caller's explicit choice.
DEFAULT_HORIZON_DAYS = 14
DEFAULT_THETA = 0.90
DEFAULT_MAX_BUNDLE_SIZE = 5
DEFAULT_MC_SAMPLES = 1500
DEFAULT_SOLVER_TIME_LIMIT_S = 60.0

# THE planning lock. Module level, one per process, deliberately not per
# instance -- core.py's globals are process-wide, so the lock protecting them
# must be too.
_PLANNING_LOCK = threading.RLock()


def planning_lock() -> threading.RLock:
    """Exposed so tests can assert the lock is actually held during a plan."""
    return _PLANNING_LOCK


@dataclass(frozen=True)
class PlanRequest:
    """The six parameters that fully determine a plan.

    No solve-affecting parameter gets a hidden server-side default at request
    time: a hidden default is exactly how two "identical" requests come to
    produce different plans. mc_samples in particular must be pinned, because
    the block count genuinely differs between 1500 and 4000 samples (different
    Monte Carlo estimates cross theta differently) -- expected behaviour, not a
    bug, but only if it is explicit.
    """

    scenario: str
    horizon_days: int = DEFAULT_HORIZON_DAYS
    theta: float = DEFAULT_THETA
    max_bundle_size: int = DEFAULT_MAX_BUNDLE_SIZE
    mc_samples: int = DEFAULT_MC_SAMPLES
    seed: int | None = None

    def cache_key(self) -> str:
        """Deterministic key over every field that changes the result."""
        payload = json.dumps(
            {
                "scenario": self.scenario,
                "horizon_days": int(self.horizon_days),
                "theta": float(self.theta),
                "max_bundle_size": int(self.max_bundle_size),
                "mc_samples": int(self.mc_samples),
                "seed": self.seed,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


class UnknownScenarioError(KeyError):
    """Raised for a scenario name the frozen dataset does not contain (-> 404)."""


class UnknownPlanError(KeyError):
    """Raised for a plan id not in the cache (-> 404)."""


@dataclass(frozen=True)
class PlanInternals:
    """The pipeline artefacts behind one plan, retained for explanation.

    Explaining a block or a refusal needs the jobs, columns, windows and solve
    result that produced the plan. Recomputing them per explanation request
    would cost a full column build, and re-solving to answer "why is this block
    here" would be worse still. They are retained here instead, deliberately
    OUTSIDE the response DTO: nothing in this object is serialised to a client.

    Bounded by PlanningService._max_internals so a long-lived process cannot
    accumulate column sets without limit (~16.7k columns per plan).
    """

    request: "PlanRequest"
    jobs: tuple[Any, ...]
    bundles: tuple[Any, ...]
    columns: tuple[Any, ...]
    windows: tuple[Any, ...]
    blocks_by_id: Mapping[str, Any]
    deferred_job_ids: tuple[str, ...]
    objective: float
    status: str
    rng_state: Mapping[str, Any]

    def job(self, job_id: str):
        for j in self.jobs:
            if j.id == job_id:
                return j
        raise KeyError(job_id)


class PlanningService:
    """Owns the context, the window cache, the plan cache and the lock."""

    def __init__(self, context: PlanningContext | None = None,
                 window_cache: WindowCache | None = None,
                 max_internals: int = 4,
                 store: PlanStore | None = None) -> None:
        self.context = context if context is not None else PlanningContext.load()
        self.windows = window_cache if window_cache is not None else WindowCache()
        # NullPlanStore by default, so every call site below is unconditional.
        self.store: PlanStore = store if store is not None else NullPlanStore()
        # A plan is identified by (snapshot_id, plan_id). Resolved once, here,
        # so a context that cannot be attributed to a snapshot fails at startup
        # rather than after a 13 s solve. Only asked when something will
        # actually be written: an unattributable tree is fine in memory.
        self.snapshot_id: int | None = (
            snapshot_id_for(self.context) if self.store.enabled
            else self.context.snapshot_id)
        self._plans: dict[str, dict[str, Any]] = {}
        self._internals: dict[str, PlanInternals] = {}
        self._internals_order: list[str] = []
        self._max_internals = max_internals
        self._plan_lock = threading.Lock()

    # -- plan cache --------------------------------------------------------

    def cached_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._plan_lock:
            plan = self._plans.get(plan_id)
        return copy.deepcopy(plan) if plan is not None else None

    @property
    def cached_plan_ids(self) -> tuple[str, ...]:
        with self._plan_lock:
            return tuple(self._plans.keys())

    # -- persistence -------------------------------------------------------

    def stored_plan(self, plan_id: str) -> dict[str, Any] | None:
        """A plan from memory, or from the store if this process never made it.

        This is what makes a plan id survive a restart. GET /plan/{id} uses it;
        plan() deliberately does NOT, because a plan read back from the database
        has no internals, and the compute path must run to rebuild them.

        A hit from the store is put in memory, so the second request for a plan
        costs nothing.
        """
        found = self.cached_plan(plan_id)
        if found is not None:
            return found
        if self.snapshot_id is None:
            return None
        restored = self.store.load_plan(plan_id, snapshot_id=self.snapshot_id)
        if restored is None:
            return None
        with self._plan_lock:
            self._plans.setdefault(plan_id, copy.deepcopy(restored))
        return restored

    def restore_plans(self, limit: int = 100) -> int:
        """Load recently persisted plans into memory. Returns how many.

        Called at startup so /health and the plan list are honest immediately
        rather than only after something asks for a specific id. Existing
        in-memory entries win: anything this process computed is newer than
        anything it reads back.
        """
        if self.snapshot_id is None:
            return 0
        restored = self.store.recent_plans(limit, snapshot_id=self.snapshot_id)
        added = 0
        with self._plan_lock:
            for payload in restored:
                if payload["plan_id"] not in self._plans:
                    self._plans[payload["plan_id"]] = payload
                    added += 1
        return added

    def internals(self, plan_id: str) -> PlanInternals:
        """Pipeline artefacts for a plan. Raises UnknownPlanError if evicted."""
        with self._plan_lock:
            found = self._internals.get(plan_id)
        if found is None:
            raise UnknownPlanError(plan_id)
        return found

    def has_internals(self, plan_id: str) -> bool:
        with self._plan_lock:
            return plan_id in self._internals

    def _store_internals(self, plan_id: str, internals: PlanInternals) -> None:
        with self._plan_lock:
            if plan_id in self._internals:
                self._internals_order.remove(plan_id)
            self._internals[plan_id] = internals
            self._internals_order.append(plan_id)
            while len(self._internals_order) > self._max_internals:
                evicted = self._internals_order.pop(0)
                self._internals.pop(evicted, None)

    # -- the planning entry point -----------------------------------------

    def plan(self, request: PlanRequest, use_cache: bool = True) -> dict[str, Any]:
        """Produce a plan. Serialised by the planning lock.

        Returns a dict shaped to API_CONTRACT.md's POST /plan response.
        """
        if not self.context.has_scenario(request.scenario):
            raise UnknownScenarioError(request.scenario)
        if not 0.0 < request.theta < 1.0:
            raise ValueError(f"theta must be in (0, 1), got {request.theta}")
        if request.horizon_days < 1:
            raise ValueError(f"horizon_days must be >= 1, got {request.horizon_days}")
        if request.mc_samples < 1:
            raise ValueError(f"mc_samples must be >= 1, got {request.mc_samples}")
        if request.max_bundle_size < 1:
            raise ValueError(
                f"max_bundle_size must be >= 1, got {request.max_bundle_size}"
            )

        plan_id = request.cache_key()
        if use_cache:
            hit = self.cached_plan(plan_id)
            # A cached response is only usable while the artefacts that explain
            # it survive. _plans is unbounded and _internals is not, so a plan
            # outlives its internals routinely -- after which every Why request
            # for it answered 409 forever, because this path returned the cached
            # DTO without ever rebuilding them. Re-planning did not help either:
            # the identical request produced this same cache key and hit here
            # again. Requiring both halves lets a stale entry fall through to the
            # compute path below, which restores internals under the same
            # plan_id. Verified safe first: the same request reproduces the same
            # concrete artefacts (block ids, job assignments, raw reliabilities)
            # in this process, so the restored internals describe the plan the
            # client is already displaying.
            #
            # The two reads take _plan_lock separately, which is deliberate --
            # a concurrent eviction between them makes this fall through and
            # recompute, which is the safe direction. Nothing here can hand back
            # a plan whose internals are known to be gone.
            if hit is not None and self.has_internals(plan_id):
                # `hit` is already a deep copy (cached_plan() makes one), so
                # this cannot mutate the stored entry. Marked explicitly rather
                # than left implicit: `stage_timings_s` below is still whatever
                # the ORIGINAL computation measured (useful evidence -- "this
                # scenario takes ~9s to solve"), and without cache_hit a caller
                # has no way to know that number is not this request's actual
                # latency. Silently reusing stale timings as if they were live
                # is exactly the kind of small dishonesty this project has
                # avoided everywhere else.
                hit["cache_hit"] = True
                return hit

        # ---- everything below runs under the lock ------------------------
        with _PLANNING_LOCK:
            timings: dict[str, float] = {}
            wall_start = time.perf_counter()

            # 1. Reset the RNG to a known state. build_columns() is the only
            #    RNG consumer in the pipeline (window generation and the traffic
            #    model are deterministic simulations), so a single reset here
            #    covers the whole plan.
            core.RNG.bit_generator.state = self.context.fresh_rng_state(request.seed)

            # 2. Reapply configuration, then the request's overrides. Reapplying
            #    matters because a previous request may have changed a global.
            started = time.perf_counter()
            from blockplan_adapter import (  # noqa: PLC0415  (kept local; see paths)
                apply_freight_scenario,
                load_config_into_core,
                load_pairing_rules_into_core,
            )

            load_config_into_core(core, paths.CONFIG_DIR)
            # The context's own tree, not the frozen constant: a context built
            # from a database snapshot must not have frozen rules reloaded
            # over the top of it before every solve.
            load_pairing_rules_into_core(core, self.context.tree.pairing_rules_csv)
            core.THETA = float(request.theta)
            timings["load_config"] = time.perf_counter() - started

            scenario_row = self.context.scenario(request.scenario)

            # 3. Windows: cached per scenario. Generated under the freight
            #    weighting inside the cache; ~13.5 s on a miss, ~0 s on a hit.
            started = time.perf_counter()
            window_set = self.windows.get(
                self.context, request.scenario, request.horizon_days,
                DEFAULT_KEEP_PER_DAY,
            )
            timings["windows"] = time.perf_counter() - started

            # 4. The pipeline. core functions, called in order, never modified.
            #    Freight weighting is active for the whole pipeline because the
            #    traffic model reads TRAIN_WEIGHT when pricing.
            original_weights = apply_freight_scenario(core, scenario_row)
            try:
                started = time.perf_counter()
                jobs = core.expand_mandatory_pairings(
                    self.context.jobs_for(request.scenario)
                )
                timings["expand_pairings"] = time.perf_counter() - started

                started = time.perf_counter()
                bundles = core.enumerate_bundles(
                    jobs, max_size=request.max_bundle_size
                )
                timings["enumerate_bundles"] = time.perf_counter() - started

                started = time.perf_counter()
                columns = core.build_columns(
                    jobs,
                    bundles,
                    list(window_set.windows),
                    theta=core.THETA,
                    mc_samples=request.mc_samples,
                )
                timings["build_columns"] = time.perf_counter() - started

                started = time.perf_counter()
                result = core.solve(
                    jobs,
                    columns,
                    list(self.context.sections),
                    request.horizon_days,
                    time_limit_s=DEFAULT_SOLVER_TIME_LIMIT_S,
                )
                timings["solve"] = time.perf_counter() - started

                summary = core.evaluate("OURS", result["blocks"], jobs)
            finally:
                core.TRAIN_WEIGHT = original_weights

            timings["total"] = time.perf_counter() - wall_start

            payload = shape_plan_response(
                plan_id=plan_id,
                request=request,
                jobs=jobs,
                bundles=bundles,
                columns=columns,
                window_set=window_set,
                result=result,
                summary=summary,
                timings=timings,
            )

            # Retained for explanation. Built inside the lock from the same
            # objects the DTO was shaped from, so a block id always refers to
            # the same column in both.
            internals = PlanInternals(
                request=request,
                jobs=tuple(jobs),
                bundles=tuple(bundles),
                columns=tuple(columns),
                windows=tuple(window_set.windows),
                blocks_by_id=block_id_map(result["blocks"]),
                deferred_job_ids=tuple(result["deferred"]),
                objective=result["objective"],
                status=result["status"],
                rng_state=self.context.fresh_rng_state(request.seed),
            )

        self._store_internals(plan_id, internals)
        with self._plan_lock:
            self._plans[plan_id] = copy.deepcopy(payload)
        self._persist(payload, internals)
        return payload

    def _persist(self, payload: Mapping[str, Any],
                 internals: PlanInternals) -> None:
        """Write the plan out, if a store is configured.

        Outside the planning lock: it is I/O against a different system and has
        no bearing on solver determinism, so holding the lock through it would
        serialise every other request behind a database round trip for no
        benefit.
        """
        if not self.store.enabled:
            return
        assert self.snapshot_id is not None   # guaranteed by __init__
        self.store.save_plan(
            payload,
            snapshot_id=self.snapshot_id,
            raw=raw_plan_values(internals),
        )


# -- DTO shaping -----------------------------------------------------------

# How many decimal places the response shows, per API_CONTRACT.md. Named rather
# than inlined because a plan restored from the database is rebuilt from the
# UNROUNDED values the solver produced, and applies these same rules on the way
# out (blockplan_db/plan_store.py). Two hand-written copies of "round to 1" is
# exactly the kind of thing that drifts silently; round-trip equality is
# asserted in tests/test_plan_persistence.py as well.
OBJECTIVE_DP = 1
RELIABILITY_DP = 3
COST_DP = 1



def block_id_map(blocks) -> dict[str, Any]:
    """Assign the stable block ids the API exposes.

    core.solve() already returns its chosen columns sorted by (day, start_min),
    so this numbering is stable for a given plan. Defined once and used by both
    the response DTO and the retained internals so the two can never disagree
    about which column "B0007" means.
    """
    return {f"B{n:04d}": column for n, column in enumerate(blocks, start=1)}


def raw_plan_values(internals: PlanInternals) -> RawPlanValues:
    """The unrounded figures behind a plan, for persistence.

    Taken from the retained solver objects rather than from the response,
    because the response has already rounded them and rounding does not
    invert. What gets stored is therefore exactly what the block fingerprint in
    tests/test_reference_plan.py is computed over.
    """
    return RawPlanValues(
        objective=internals.objective,
        blocks={
            block_id: (column.reliability, column.window.traffic_cost,
                       column.exp_overrun_cost)
            for block_id, column in internals.blocks_by_id.items()
        },
    )


def shape_plan_response(*, plan_id: str, request: PlanRequest, jobs, bundles,
                        columns, window_set, result: Mapping[str, Any],
                        summary: Mapping[str, Any],
                        timings: Mapping[str, float]) -> dict[str, Any]:
    """Shape core's output into API_CONTRACT.md's POST /plan response.

    Field names here are the contract's. core.evaluate()'s dict is passed
    through as `summary` without renaming, so there is no translation layer to
    keep in sync.
    """
    index = {j.id: j for j in jobs}

    blocks = []
    for block_id, column in block_id_map(result["blocks"]).items():
        window = column.window
        depts = sorted({index[jid].dept for jid in column.job_ids})
        blocks.append(
            {
                "block_id": block_id,
                "section_id": window.section_id,
                "day": window.day,
                "start_min": window.start_min,
                "length": window.length,
                "end_min": window.end_min,
                "reliability": round(column.reliability, RELIABILITY_DP),
                "traffic_cost": round(window.traffic_cost, COST_DP),
                "exp_overrun_cost": round(column.exp_overrun_cost, COST_DP),
                "dept_mix": depts,
                "job_ids": list(column.job_ids),
            }
        )

    deferred = [
        {"job_id": jid, "dept": index[jid].dept}
        for jid in result["deferred"]
        if jid in index
    ]

    # core.evaluate() also returns `method` (the label it was called with, here
    # always "OURS"). It is dropped rather than passed through: the contract
    # documents summary without it, and a field whose value is constant across
    # every response is noise on the wire.
    summary_out = {k: v for k, v in summary.items() if k != "method"}

    return {
        "plan_id": plan_id,
        "scenario": request.scenario,
        "horizon_days": request.horizon_days,
        "theta": request.theta,
        # Always False here: this function runs only on the fresh-compute
        # path. A cache hit never reaches it -- plan() returns straight from
        # cached_plan() before shape_plan_response is called -- and sets this
        # to True itself on the dict it returns instead.
        "cache_hit": False,
        "status": result["status"],
        "objective": round(result["objective"], OBJECTIVE_DP),
        "blocks": blocks,
        "deferred": deferred,
        "summary": summary_out,
        "stage_timings_s": {k: round(v, 3) for k, v in timings.items()},
        "instance": {
            "base_jobs": sum(1 for j in jobs if not j.is_companion),
            "jobs_after_pairing": len(jobs),
            "bundles": len(bundles),
            "windows": len(window_set.windows),
            "columns": len(columns),
            "mc_samples": request.mc_samples,
            "max_bundle_size": request.max_bundle_size,
            "seed": request.seed,
        },
    }
