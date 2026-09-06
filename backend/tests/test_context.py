"""PlanningContext behaviour."""
from __future__ import annotations

import dataclasses

import pytest

from blockplan_service import PlanningContext

EXPECTED_SCENARIOS = {
    "NORMAL_TRAFFIC",
    "PEAK_TRAFFIC",
    "HEAVY_FREIGHT",
    "MAINTENANCE_BACKLOG",
    "URGENT_MAINTENANCE",
    "HIGH_DURATION_UNCERTAINTY",
    "DISRUPTED_OPERATION",
    "MULTIPLE_DEPARTMENT_REQUESTS",
}


def test_loads_all_eight_scenarios(context: PlanningContext):
    assert set(context.scenario_names) == EXPECTED_SCENARIOS


def test_loads_the_frozen_corridor(context: PlanningContext):
    # 26 physical sections x UP/DN
    assert len(context.sections) == 52
    assert len(context.section_ids) == 52
    assert context.trains, "no train movements loaded"


def test_base_job_counts_match_the_frozen_dataset(context: PlanningContext):
    # From the frozen scenario_jobs_manifest.
    assert context.base_job_count("NORMAL_TRAFFIC") == 175
    assert context.base_job_count("MAINTENANCE_BACKLOG") == 340
    assert context.base_job_count("DISRUPTED_OPERATION") == 222
    assert context.base_job_count("MULTIPLE_DEPARTMENT_REQUESTS") == 236


def test_pairing_rules_are_loaded(context: PlanningContext):
    # Six mandatory pairing rules in the frozen CSV. Expanding with an empty
    # rule table would silently produce single-department bundles.
    assert context.pairing_rule_count == 6


def test_context_is_frozen(context: PlanningContext):
    assert dataclasses.is_dataclass(context)
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.sections = ()  # type: ignore[misc]


def test_unknown_scenario_raises(context: PlanningContext):
    with pytest.raises(KeyError):
        context.scenario("NO_SUCH_SCENARIO")
    with pytest.raises(KeyError):
        context.jobs_for("NO_SUCH_SCENARIO")
    assert not context.has_scenario("NO_SUCH_SCENARIO")


def test_jobs_for_returns_independent_copies(context: PlanningContext, core_module):
    """The context must not be mutated by planning.

    core.expand_mandatory_pairings() assigns `j.companions` on the jobs it is
    given. If the context handed out its stored objects, the first plan would
    mutate it permanently -- so this is the test that the "immutable after
    startup" guarantee actually holds.
    """
    first = context.jobs_for("NORMAL_TRAFFIC")
    assert all(j.companions == () for j in first), "context handed out pre-expanded jobs"

    core_module.expand_mandatory_pairings(first)
    assert any(j.companions for j in first), "expansion did not set companions"

    second = context.jobs_for("NORMAL_TRAFFIC")
    assert all(j.companions == () for j in second), (
        "expansion leaked into the context: jobs_for() is not returning copies"
    )
    assert first[0] is not second[0]


def test_trains_for_peak_adds_paths_others_unchanged(context: PlanningContext):
    base = len(context.trains)
    assert len(context.trains_for("NORMAL_TRAFFIC")) == base
    assert len(context.trains_for("PEAK_TRAFFIC")) > base, (
        "PEAK_TRAFFIC should add synthetic passenger paths"
    )


def test_fresh_rng_state_is_a_copy(context: PlanningContext):
    a = context.fresh_rng_state()
    b = context.fresh_rng_state()
    assert a == b
    assert a is not b

    seeded = context.fresh_rng_state(seed=12345)
    assert seeded != a, "an explicit seed should differ from the pristine state"
