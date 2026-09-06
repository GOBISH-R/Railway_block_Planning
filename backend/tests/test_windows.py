"""Window cache: key correctness, invalidation, and RNG neutrality."""
from __future__ import annotations

import copy

from blockplan_service import WindowCache
from blockplan_service.windows import DEFAULT_KEEP_PER_DAY, key_for


def test_key_is_deterministic(context):
    row = context.scenario("NORMAL_TRAFFIC")
    assert key_for(row, 14) == key_for(row, 14)
    assert hash(key_for(row, 14)) == hash(key_for(row, 14))


def test_key_separates_the_parameters_that_change_the_result(context):
    row = context.scenario("NORMAL_TRAFFIC")
    base = key_for(row, 14)

    assert key_for(row, 7) != base, "horizon must be part of the key"
    assert key_for(row, 14, keep_per_day=4) != base, "keep_per_day must be part of the key"

    # Scenarios differing in the parameters that drive window supply must not
    # share a cache entry.
    assert key_for(context.scenario("HEAVY_FREIGHT"), 14) != base
    assert key_for(context.scenario("PEAK_TRAFFIC"), 14) != base
    assert key_for(context.scenario("DISRUPTED_OPERATION"), 14) != base


def test_key_captures_scenario_parameters_not_just_the_name(context):
    """The key carries freight/passenger/cancellation explicitly.

    A key of scenario-name-only would be wrong the moment a scenario's declared
    parameters changed without its name changing.
    """
    key = key_for(context.scenario("HEAVY_FREIGHT"), 14)
    assert key.freight_scale == 2.0
    assert key_for(context.scenario("DISRUPTED_OPERATION"), 14).cancel_window_fraction == 0.25
    assert key_for(context.scenario("PEAK_TRAFFIC"), 14).extra_passenger_scale == 1.35


def test_cache_hits_and_misses(service):
    cache = service.windows
    before_hits, before_misses = cache.hits, cache.misses

    first = cache.get(service.context, "NORMAL_TRAFFIC", 14)
    second = cache.get(service.context, "NORMAL_TRAFFIC", 14)

    assert second is first, "second lookup should return the cached object"
    assert cache.hits > before_hits
    # At most one new generation for this key across both calls.
    assert cache.misses - before_misses <= 1


def test_window_count_matches_the_frozen_benchmark(service):
    """11,648 candidate windows for NORMAL_TRAFFIC, per benchmark_results.csv."""
    window_set = service.windows.get(service.context, "NORMAL_TRAFFIC", 14)
    assert len(window_set.windows) == 11648


def test_disrupted_scenario_withdraws_windows(service):
    normal = service.windows.get(service.context, "NORMAL_TRAFFIC", 14)
    disrupted = service.windows.get(service.context, "DISRUPTED_OPERATION", 14)
    assert disrupted.kept_count < disrupted.generated_count, (
        "DISRUPTED_OPERATION should withdraw part of the window supply"
    )
    assert len(disrupted.windows) < len(normal.windows)


def test_window_generation_does_not_disturb_the_rng(service, core_module):
    """The architecture depends on this.

    The planner resets the RNG once, before the pipeline. If window generation
    consumed RNG draws, then a cache MISS and a cache HIT would leave the RNG
    in different states by the time build_columns() runs, and the same request
    would produce different plans depending on cache state -- an
    irreproducibility that would be very hard to diagnose.
    """
    cache = WindowCache()  # deliberately empty: forces a real generation
    core_module.RNG.bit_generator.state = service.context.fresh_rng_state()
    before = copy.deepcopy(core_module.RNG.bit_generator.state)

    cache.get(service.context, "NORMAL_TRAFFIC", 14)

    assert core_module.RNG.bit_generator.state == before, (
        "generate_windows consumed RNG draws; the single pre-pipeline reset is "
        "no longer sufficient"
    )


def test_cached_windows_equal_freshly_generated(service):
    """A cache hit must be indistinguishable from regenerating."""
    cached = service.windows.get(service.context, "NORMAL_TRAFFIC", 14)

    fresh_cache = WindowCache()
    fresh = fresh_cache.get(service.context, "NORMAL_TRAFFIC", 14)

    assert len(fresh.windows) == len(cached.windows)
    assert [(w.section_id, w.day, w.start_min, w.length, w.traffic_cost)
            for w in fresh.windows] == \
           [(w.section_id, w.day, w.start_min, w.length, w.traffic_cost)
            for w in cached.windows]


def test_clear_empties_the_cache(service):
    cache = WindowCache()
    cache.get(service.context, "NORMAL_TRAFFIC", 14)
    assert cache.size == 1
    cache.clear()
    assert cache.size == 0
    assert cache.hits == 0 and cache.misses == 0
