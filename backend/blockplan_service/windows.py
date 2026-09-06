"""Window cache.

generate_windows() is ~13.5 s -- roughly three quarters of a cold plan, more
than everything else combined. It runs the priority-queue traffic simulation
across 52 section-lines x 14 days x 2 block lengths x 48 start offsets.

Its inputs are only (sections, trains, horizon, keep_per_day). It does not
depend on the maintenance jobs, theta, bundle size, mc_samples, or anything
else a user can change from the UI. The only user-facing thing that moves it is
the SCENARIO, because a scenario can change the train set (PEAK_TRAFFIC adds
passenger paths) and the traffic weighting (HEAVY_FREIGHT re-weights freight).

So there are exactly eight window sets in the whole system, one per scenario.
Caching them is what makes a synchronous HTTP endpoint viable and removes the
entire job-queue/worker/websocket layer from the architecture. Without this
cache every request costs ~18 s and the tool looks like it has hung.

Window generation consumes no RNG: it is a deterministic queue simulation. The
cache therefore cannot leak randomness between requests.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from . import paths

paths.ensure_import_paths()

import core  # noqa: E402
from blockplan_adapter import (  # noqa: E402
    apply_freight_scenario,
    remove_disrupted_windows,
)

# The benchmark's window-supply setting. Part of the cache key rather than a
# constant, so a caller that changes it cannot silently receive another
# setting's windows.
DEFAULT_KEEP_PER_DAY = 8


@dataclass(frozen=True)
class WindowCacheKey:
    """Everything that changes the generated window set, and nothing else.

    scenario is in the key because it determines both the train set
    (extra_passenger_scale) and the traffic weighting (freight_scale), and
    because cancel_window_fraction withdraws part of the supply afterwards.
    Including the scenario name alone would be a bug if two scenarios shared a
    name but differed in parameters, so the three parameters that actually
    matter are carried explicitly.
    """

    scenario: str
    horizon_days: int
    keep_per_day: int
    freight_scale: float
    extra_passenger_scale: float
    cancel_window_fraction: float


@dataclass(frozen=True)
class WindowSet:
    windows: tuple[Any, ...]
    key: WindowCacheKey
    seconds: float
    generated_count: int      # before disruption withdrawal
    kept_count: int           # after disruption withdrawal


def _float_or(value: Any, default: float) -> float:
    """Mirror of the adapter's own blank-field handling."""
    if value is None or value == "":
        return default
    return float(value)


def key_for(scenario_row: Mapping[str, Any], horizon_days: int,
            keep_per_day: int = DEFAULT_KEEP_PER_DAY) -> WindowCacheKey:
    return WindowCacheKey(
        scenario=scenario_row["scenario"],
        horizon_days=int(horizon_days),
        keep_per_day=int(keep_per_day),
        freight_scale=_float_or(scenario_row.get("freight_scale"), 1.0),
        extra_passenger_scale=_float_or(scenario_row.get("extra_passenger_scale"), 1.0),
        cancel_window_fraction=_float_or(scenario_row.get("cancel_window_fraction"), 0.0),
    )


class WindowCache:
    """Lazy, thread-safe, process-local cache of scenario window sets.

    Deliberately in-memory only. The dataset is frozen and read-only, there is
    one process, and a disk cache would be a second copy of something derived
    from files that do not change -- with a staleness question attached. Warming
    all eight sets at startup is Phase 8's packaging concern; the lazy path is
    correct either way.
    """

    def __init__(self) -> None:
        self._sets: dict[WindowCacheKey, WindowSet] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    # -- statistics (for tests and diagnostics) ----------------------------

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def size(self) -> int:
        return len(self._sets)

    def keys(self) -> tuple[WindowCacheKey, ...]:
        return tuple(self._sets.keys())

    # -- the cache ---------------------------------------------------------

    def get(self, context, scenario_name: str, horizon_days: int,
            keep_per_day: int = DEFAULT_KEEP_PER_DAY) -> WindowSet:
        """Return the window set for this scenario, generating it if needed.

        The caller is expected to already hold the planning lock: window
        generation prices windows with core.TRAIN_WEIGHT, which
        apply_freight_scenario mutates, so this must not run concurrently with
        another scenario's plan. The internal lock protects the dict itself,
        not that global.
        """
        scenario_row = context.scenario(scenario_name)
        key = key_for(scenario_row, horizon_days, keep_per_day)

        with self._lock:
            cached = self._sets.get(key)
        if cached is not None:
            self._hits += 1
            return cached

        self._misses += 1
        window_set = self._generate(context, scenario_row, key)
        with self._lock:
            self._sets[key] = window_set
        return window_set

    def _generate(self, context, scenario_row: Mapping[str, Any],
                  key: WindowCacheKey) -> WindowSet:
        trains = context.trains_for(key.scenario)

        # HEAVY_FREIGHT re-weights freight, and that weighting must be active
        # while windows are priced -- the traffic model reads core.TRAIN_WEIGHT
        # inside generate_windows. Restored in the finally block so one
        # scenario can never colour another.
        original_weights = apply_freight_scenario(core, scenario_row)
        started = time.perf_counter()
        try:
            windows = core.generate_windows(
                list(context.sections),
                trains,
                key.horizon_days,
                keep_per_day=key.keep_per_day,
            )
        finally:
            core.TRAIN_WEIGHT = original_weights
        generated = len(windows)

        # DISRUPTED_OPERATION withdraws a deterministic subset afterwards.
        windows = remove_disrupted_windows(windows, scenario_row)
        seconds = time.perf_counter() - started

        return WindowSet(
            windows=tuple(windows),
            key=key,
            seconds=seconds,
            generated_count=generated,
            kept_count=len(windows),
        )

    def warm(self, context, horizon_days: int,
             keep_per_day: int = DEFAULT_KEEP_PER_DAY) -> None:
        """Precompute every scenario's window set (~90 s for all eight)."""
        for name in context.scenario_names:
            self.get(context, name, horizon_days, keep_per_day)

    def clear(self) -> None:
        with self._lock:
            self._sets.clear()
        self._hits = 0
        self._misses = 0
