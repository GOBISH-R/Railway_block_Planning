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


class PlanningService:
    """Owns the context, the window cache, the plan cache and the lock."""

    def __init__(self, context: PlanningContext | None = None,
                 window_cache: WindowCache | None = None) -> None:
        self.context = context if context is not None else PlanningContext.load()
        self.windows = window_cache if window_cache is not None else WindowCache()
        self._plans: dict[str, dict[str, Any]] = {}
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
            if hit is not None:
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
            load_pairing_rules_into_core(core, paths.PAIRING_RULES_CSV)
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

        with self._plan_lock:
            self._plans[plan_id] = copy.deepcopy(payload)
        return payload


# -- DTO shaping -----------------------------------------------------------

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
    for n, column in enumerate(result["blocks"], start=1):
        window = column.window
        depts = sorted({index[jid].dept for jid in column.job_ids})
        blocks.append(
            {
                "block_id": f"B{n:04d}",
                "section_id": window.section_id,
                "day": window.day,
                "start_min": window.start_min,
                "length": window.length,
                "end_min": window.end_min,
                "reliability": round(column.reliability, 3),
                "traffic_cost": round(window.traffic_cost, 1),
                "exp_overrun_cost": round(column.exp_overrun_cost, 1),
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
        "status": result["status"],
        "objective": round(result["objective"], 1),
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
