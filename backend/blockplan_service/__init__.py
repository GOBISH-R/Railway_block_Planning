"""BlockPlan planning service.

Layers, per the project architecture:

    api/       blockplan_api/ -- FastAPI + Pydantic v2, routing and validation
    service/   planner.py  -- THE LOCK, plan cache, pipeline, DTO shaping
               explain.py  -- explanation service (blocks and refusals)
               windows.py  -- window cache
               persistence.py -- whether plans are written anywhere
    context/   context.py     -- PlanningContext, the tables read once
               datasource.py  -- WHERE that tree comes from: CSVs or PostgreSQL
    core.py    FROZEN -- imported, never edited

Nothing in this package reimplements optimisation logic. It orchestrates the
frozen core and reuses the existing blockplan_adapter loaders.
"""
from . import asset_impact
from .context import PlanningContext
from .datasource import (
    CsvDataSource,
    DatabaseDataSource,
    DataSource,
    DataSourceError,
    resolve as resolve_data_source,
)
from .persistence import (
    NullPlanStore,
    PersistenceError,
    PlanStore,
    RawPlanValues,
    resolve as resolve_plan_store,
    snapshot_id_for,
)
from .explain import (
    ExplanationService,
    ExplanationUnavailableError,
    UnknownBlockError,
    UnknownJobError,
    departmental_chains,
)
from .planner import (
    PlanInternals,
    PlanningService,
    PlanRequest,
    UnknownPlanError,
    UnknownScenarioError,
    planning_lock,
    shape_plan_response,
)
from .windows import WindowCache, WindowCacheKey, WindowSet

__all__ = [
    "PlanningContext",
    "asset_impact",
    "CsvDataSource",
    "DataSource",
    "DataSourceError",
    "DatabaseDataSource",
    "resolve_data_source",
    "NullPlanStore",
    "PersistenceError",
    "PlanStore",
    "RawPlanValues",
    "resolve_plan_store",
    "snapshot_id_for",
    "ExplanationService",
    "ExplanationUnavailableError",
    "PlanInternals",
    "UnknownBlockError",
    "UnknownJobError",
    "UnknownPlanError",
    "departmental_chains",
    "PlanningService",
    "PlanRequest",
    "UnknownScenarioError",
    "planning_lock",
    "shape_plan_response",
    "WindowCache",
    "WindowCacheKey",
    "WindowSet",
]
