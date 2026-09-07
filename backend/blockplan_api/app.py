"""FastAPI application — the nine-endpoint surface in API_CONTRACT.md.

    GET  /corridor                               static corridor geography
    GET  /scenarios                               the eight scenarios
    GET  /demand                                  maintenance demand for one scenario
    GET  /traffic                                 train movements for one scenario
    POST /plan                                    create a plan
    GET  /plan/{plan_id}                          re-serve it
    GET  /plan/{plan_id}/block/{block_id}         why this block
    POST /plan/{plan_id}/explain/{job_id}         why this job
    GET  /comparison                              the frozen benchmark artefacts

This layer contains no planning logic. It routes, validates and maps errors.
Per the frozen error semantics, "no feasible plan" is a 200 with an empty block
list, never a 500 -- a plan in which everything is deferred at theta = 0.99 is
the tool working correctly and saying so. The five data-serving endpoints
contain no optimisation logic either: they read PlanningContext or the frozen
CSVs directly and shape the result, reusing the existing blockplan_adapter
loaders and reference_data.py rather than duplicating any of it.

Packaging (Phase 8): when frontend/dist/ exists, this same app also serves it
as static files, so the whole system is one process on one port with no
network dependency at demo time. See BLOCKPLAN_WARM_ON_STARTUP below for how
cold-start latency is avoided without slowing down the test suite.
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Path, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from blockplan_service import PlanningService, PlanRequest, paths  # noqa: E402
from blockplan_service.explain import (  # noqa: E402
    ExplanationService,
    ExplanationUnavailableError,
    UnknownBlockError,
    UnknownJobError,
)
from blockplan_service.persistence import resolve as resolve_plan_store  # noqa: E402
from blockplan_service.planner import UnknownPlanError, UnknownScenarioError  # noqa: E402
from blockplan_service import reference_data  # noqa: E402

from .schemas import (  # noqa: E402
    BlockExplanation,
    ErrorResponse,
    JobExplanation,
    PlanRequestModel,
)

_state: dict[str, Any] = {}

# Precomputing all eight scenarios' plans at startup takes a few minutes (each
# pays a cold window-generation cost the first time it is touched). That is
# exactly right for "start once before the demo, offline from then on" --
# and exactly wrong for a test suite that constructs a fresh TestClient (and
# therefore a fresh lifespan) many times across ~10 test files. Gating it
# behind an environment variable keeps `pytest` at its current ~5 minutes for
# 96 tests instead of multiplying that by however many test files touch the
# app fixture.
def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


WARM_ON_STARTUP = _env_flag("BLOCKPLAN_WARM_ON_STARTUP")


def get_planning_service() -> PlanningService:
    return _state["planning"]


def get_explanation_service() -> ExplanationService:
    return _state["explanation"]


def _warm_all_scenarios(planning: PlanningService) -> None:
    """Precompute every scenario's windows and default-parameter plan.

    core.py's own project memory is explicit about why this matters: window
    generation is ~75% of a cold plan and depends only on
    (sections, trains, horizon) -- never on theta, bundle size or mc_samples --
    so there are exactly eight window sets in the whole system. Computing all
    eight, and the default plan built from each, once at startup is what makes
    every subsequent scenario switch in the UI instant instead of paying that
    cost live in front of a judge.

    PlanRequest()'s own defaults (theta=0.90, horizon=14, max_bundle_size=5,
    mc_samples=1500) are deliberately identical to the frontend's initial
    state, so the plan precomputed here is exactly the one the UI requests
    the first time a user selects that scenario.
    """
    names = planning.context.scenario_names
    print(f"[warmup] precomputing {len(names)} scenarios...", flush=True)
    for name in names:
        started = time.perf_counter()
        planning.plan(PlanRequest(scenario=name))
        print(f"[warmup]   {name}: {time.perf_counter() - started:.1f}s", flush=True)
    print("[warmup] done -- every scenario's default plan is cached.", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the frozen dataset once, at startup, not per request."""
    # 12, not 8: the eight precomputed scenario plans plus headroom for a few
    # live re-plans (a controller dragging theta during the demo) before the
    # oldest internals are evicted. Still bounded, not unlimited growth.
    planning = PlanningService(max_internals=12, store=resolve_plan_store())
    _state["planning"] = planning
    _state["explanation"] = ExplanationService(planning)
    if planning.store.enabled:
        # Plans made before this process started. Without this the ids handed
        # out by the previous run are 404 until something asks for one by name.
        restored = planning.restore_plans()
        print(f"[startup] {planning.store.describe()}; "
              f"restored {restored} plan(s)", flush=True)
    if WARM_ON_STARTUP:
        _warm_all_scenarios(planning)
    yield
    _state.clear()


app = FastAPI(
    title="BlockPlan",
    version="0.3.0",
    summary=(
        "Constraint-optimisation and stochastic-simulation decision support for "
        "railway block planning."
    ),
    lifespan=lifespan,
)

# Needed only for `npm run dev` (Vite on a different port talking to this
# backend directly, bypassing its own dev proxy if opened without it). The
# packaged app (frontend/dist served by this same process, below) is
# same-origin and does not need CORS at all -- this middleware is harmless
# there, not load-bearing. No credentials are used, so an open origin list
# carries no session/cookie exposure either way.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_ERRORS = {404: {"model": ErrorResponse}}
_EXPLAIN_ERRORS = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}}


# -- data-serving endpoints (no planning logic) -----------------------------

@app.get("/corridor")
def get_corridor() -> dict[str, Any]:
    return reference_data.corridor_payload(get_planning_service().context)


@app.get("/scenarios")
def get_scenarios() -> dict[str, Any]:
    return reference_data.scenarios_payload(get_planning_service().context)


@app.get("/demand", responses=_ERRORS)
def get_demand(scenario: str = Query(..., min_length=1)) -> dict[str, Any]:
    try:
        return reference_data.demand_payload(get_planning_service().context, scenario)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"unknown scenario: {scenario}") from exc


@app.get("/traffic", responses=_ERRORS)
def get_traffic(scenario: str = Query(..., min_length=1),
               section_id: str | None = Query(None)) -> dict[str, Any]:
    try:
        return reference_data.traffic_payload(
            get_planning_service().context, scenario, section_id
        )
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"unknown scenario: {scenario}") from exc


@app.get("/comparison")
def get_comparison() -> dict[str, Any]:
    return reference_data.comparison_payload()


@app.post("/plan", responses=_ERRORS)
def create_plan(body: PlanRequestModel) -> dict[str, Any]:
    """Run the full planning pipeline under the planning lock.

    Synchronous by design: with the window cache warm this is a single blocking
    call, which is what removes the entire job-queue and websocket layer from
    the architecture.
    """
    service = get_planning_service()
    try:
        return service.plan(
            PlanRequest(
                scenario=body.scenario,
                horizon_days=body.horizon_days,
                theta=body.theta,
                max_bundle_size=body.max_bundle_size,
                mc_samples=body.mc_samples,
                seed=body.seed,
            )
        )
    except UnknownScenarioError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"unknown scenario: {exc.args[0]}") from exc
    except ValueError as exc:
        # Defence in depth. Pydantic rejects these first; if one reaches here the
        # models and the service have drifted apart.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@app.get("/plan/{plan_id}", responses=_ERRORS)
def get_plan(plan_id: str = Path(..., min_length=1)) -> dict[str, Any]:
    # stored_plan, not cached_plan: a plan produced before a restart lives in
    # PostgreSQL when persistence is on, and its id must keep working.
    plan = get_planning_service().stored_plan(plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown plan: {plan_id}")
    return plan


@app.get("/plan/{plan_id}/block/{block_id}",
         response_model=BlockExplanation, responses=_EXPLAIN_ERRORS)
def explain_block(plan_id: str = Path(..., min_length=1),
                  block_id: str = Path(..., min_length=1)) -> Any:
    """Why this block: its jobs, departments, chains, envelope and constraints.

    Runs no solver and consumes no RNG.
    """
    try:
        return get_explanation_service().explain_block(plan_id, block_id)
    except UnknownPlanError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"unknown plan: {plan_id}") from exc
    except ExplanationUnavailableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UnknownBlockError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"unknown block: {block_id}") from exc


@app.post("/plan/{plan_id}/explain/{job_id}",
          response_model=JobExplanation, responses=_EXPLAIN_ERRORS)
def explain_job(plan_id: str = Path(..., min_length=1),
                job_id: str = Path(..., min_length=1)) -> Any:
    """Why this job was scheduled, or why it was refused.

    Cost is not uniform and the response says which case applied: the
    INFEASIBLE branch answers immediately, while OUTBID re-solves the model with
    the job forced in to price the insertion. A client should show a spinner
    only for the second.
    """
    try:
        return get_explanation_service().explain_job(plan_id, job_id)
    except UnknownPlanError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"unknown plan: {plan_id}") from exc
    except ExplanationUnavailableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except UnknownJobError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"unknown job: {job_id}") from exc


@app.get("/health", include_in_schema=False)
def health() -> dict[str, Any]:
    service = get_planning_service()
    return {
        "status": "ok",
        # Which tree the planner is actually reading. Worth surfacing: a
        # database-backed process and a CSV-backed one are otherwise
        # indistinguishable from the outside, by design.
        "data_source": service.context.source_description,
        "plan_store": service.store.describe(),
        "scenarios": len(service.context.scenario_names),
        "sections": len(service.context.sections),
        "window_sets_cached": service.windows.size,
        "cached_plans": len(service.cached_plan_ids),
    }


# Static frontend, mounted LAST so it never shadows an API route above: FastAPI
# checks routes in registration order, and every /corridor, /plan, /comparison
# etc. route was already registered by the time this mount is added, so a
# request for one of them matches its explicit route and never reaches this
# catch-all. Guarded on the directory existing so `pytest` and a bare backend
# checkout (no `npm install`/`npm run build` yet) keep working without it --
# this is packaging, not a hard dependency of the API.
if os.path.isdir(paths.FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=paths.FRONTEND_DIST, html=True), name="frontend")
