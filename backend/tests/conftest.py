"""Shared fixtures.

The context and window cache are session-scoped on purpose: window generation
is ~13.5 s per scenario and the whole point of Phase 1 is that it happens once.
Rebuilding it per test would make the suite unusable and would also stop it
exercising the cache at all.
"""
from __future__ import annotations

import os
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from blockplan_service import PlanningContext, PlanningService  # noqa: E402

BENCHMARK_SCENARIO = "NORMAL_TRAFFIC"


@pytest.fixture(scope="session")
def context() -> PlanningContext:
    return PlanningContext.load()


@pytest.fixture(scope="session")
def service(context: PlanningContext) -> PlanningService:
    return PlanningService(context=context)


@pytest.fixture(scope="session")
def core_module():
    from blockplan_service import paths

    paths.ensure_import_paths()
    import core

    return core
