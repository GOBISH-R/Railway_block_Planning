"""BlockPlan planning service (Phase 1).

Layers, per the project architecture:

    api/       FastAPI + Pydantic          (Phase 2 -- not built yet)
    service/   planner.py  -- THE LOCK, plan cache, pipeline, DTO shaping
               windows.py  -- window cache
    context/   context.py  -- PlanningContext, frozen CSVs read once
    core.py    FROZEN -- imported, never edited

Nothing in this package reimplements optimisation logic. It orchestrates the
frozen core and reuses the existing blockplan_adapter loaders.
"""
from .context import PlanningContext
from .planner import (
    PlanningService,
    PlanRequest,
    UnknownScenarioError,
    planning_lock,
    shape_plan_response,
)
from .windows import WindowCache, WindowCacheKey, WindowSet

__all__ = [
    "PlanningContext",
    "PlanningService",
    "PlanRequest",
    "UnknownScenarioError",
    "planning_lock",
    "shape_plan_response",
    "WindowCache",
    "WindowCacheKey",
    "WindowSet",
]
