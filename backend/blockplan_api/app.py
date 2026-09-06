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
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Path, Query, status
from fastapi.middleware.cors import CORSMiddleware

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from blockplan_service import PlanningService, PlanRequest  # noqa: E402
from blockplan_service.explain import (  # noqa: E402
    ExplanationService,
    ExplanationUnavailableError,
    UnknownBlockError,
    UnknownJobError,
)
from blockplan_service.planner import UnknownPlanError, UnknownScenarioError  # noqa: E402
from blockplan_service import reference_data  # noqa: E402

from .schemas import (  # noqa: E402
    BlockExplanation,
    ErrorResponse,
    JobExplanation,
    PlanRequestModel,
)

_state: dict[str, Any] = {}


def get_planning_service() -> PlanningService:
    return _state["planning"]


def get_explanation_service() -> ExplanationService:
    return _state["explanation"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the frozen dataset once, at startup, not per request."""
    planning = PlanningService()
    _state["planning"] = planning
    _state["explanation"] = ExplanationService(planning)
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

# The frontend is a Vite dev server on a different origin during development
# (Phase 5 wires a dev proxy so this becomes same-origin; until then CORS is
# needed to develop against a live backend at all). No credentials are used,
# so an open origin list carries no session/cookie exposure.
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
    plan = get_planning_service().cached_plan(plan_id)
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
        "scenarios": len(service.context.scenario_names),
        "sections": len(service.context.sections),
        "window_sets_cached": service.windows.size,
    }
