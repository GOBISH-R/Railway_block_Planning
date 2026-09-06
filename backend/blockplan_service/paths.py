"""Filesystem locations of the frozen assets, and sys.path wiring.

Every path this project needs is resolved here so that no other module has to
know where the frozen tree lives. Nothing in this file writes anything.
"""
from __future__ import annotations

import os
import sys

# backend/blockplan_service/paths.py -> backend/blockplan_service -> backend -> repo root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The built frontend (Phase 8 packaging). Not required to exist: the backend
# and its test suite must keep working standalone (e.g. in CI, or a backend
# developer who has never run `npm install`) whether or not anyone has built
# the frontend yet.
FRONTEND_DIST = os.path.join(REPO_ROOT, "frontend", "dist")

DATASET_TREE = os.path.join(REPO_ROOT, "Dataset")
CORE_DIR = os.path.join(DATASET_TREE, "blockplan")
DATASET_ROOT = os.path.join(DATASET_TREE, "blockplan-dataset")

ADAPTER_DIR = os.path.join(DATASET_ROOT, "src")
CONFIG_DIR = os.path.join(DATASET_ROOT, "config")
DATASET_DIR = os.path.join(DATASET_ROOT, "dataset")
PROCESSED_DIR = os.path.join(DATASET_DIR, "processed")
SCENARIOS_DIR = os.path.join(DATASET_DIR, "scenarios")

CORE_PY = os.path.join(CORE_DIR, "core.py")
PAIRING_RULES_CSV = os.path.join(PROCESSED_DIR, "pairing_rules.csv")
SECTIONS_CSV = os.path.join(PROCESSED_DIR, "sections.csv")
STATIONS_CSV = os.path.join(PROCESSED_DIR, "stations.csv")
MOVEMENTS_CSV = os.path.join(PROCESSED_DIR, "movements.csv")
SCENARIOS_CSV = os.path.join(SCENARIOS_DIR, "scenarios.csv")
SCENARIO_JOBS_DIR = os.path.join(SCENARIOS_DIR, "jobs")
METHOD_COMPARISON_CSV = os.path.join(SCENARIOS_DIR, "method_comparison.csv")
BENCHMARK_RESULTS_CSV = os.path.join(SCENARIOS_DIR, "benchmark_results.csv")
EXECUTION_SCORING_SUMMARY_CSV = os.path.join(SCENARIOS_DIR, "execution_scoring_summary.csv")

# core.py's frozen identity. CLAUDE.md and the project memory both cite these;
# the tests assert against them so an accidental edit fails loudly.
CORE_PY_BYTES = 44044
CORE_PY_SHA256 = "20a240cc4979a8231b5405cbfecb84a57a957e2bcbff19166c48c88ef2d5d054"


def scenario_jobs_csv(scenario_name: str) -> str:
    return os.path.join(SCENARIO_JOBS_DIR, f"jobs_{scenario_name}.csv")


def ensure_import_paths() -> None:
    """Put the frozen core and the adapter on sys.path.

    core.py is imported as a top-level module named `core` because
    blockplan_adapter.py imports it that way, and the adapter is reused rather
    than rewritten.
    """
    for path in (CORE_DIR, ADAPTER_DIR):
        if path not in sys.path:
            sys.path.insert(0, path)
