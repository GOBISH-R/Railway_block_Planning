"""PlanningContext -- the frozen CSVs, read once, held immutably.

This is the layer the project memory names as the single future integration
point: today it reads frozen CSVs; a division deploying this would point it at
the control office application, BDMS and the WTT, and nothing above or below it
would change.

Responsibilities (and their limits):
  - load the frozen tables ONCE at startup, reusing the existing
    blockplan_adapter loaders rather than reimplementing CSV handling
  - hand out per-request COPIES of mutable domain objects so the context
    itself is never mutated after startup
  - remember the pristine RNG state so the planner can reset determinism

It contains no planning logic and no optimisation logic.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from . import paths

paths.ensure_import_paths()

import core  # noqa: E402  (frozen analytical core -- imported, never edited)
from blockplan_adapter import (  # noqa: E402  (existing loaders, reused verbatim)
    add_peak_passenger_traffic,
    load_config_into_core,
    load_pairing_rules_into_core,
    load_scenario_jobs,
    load_scenarios,
    load_sections,
    load_trains,
)

DEFAULT_HORIZON_DAYS = 14


@dataclass(frozen=True)
class PlanningContext:
    """Immutable snapshot of the frozen dataset.

    Mutable domain objects (`core.Job`) are never handed out directly -- see
    `jobs_for()`. `core.Section`, `core.Train` and `core.Window` are all
    frozen dataclasses and are safe to share.
    """

    sections: tuple[Any, ...]
    trains: tuple[Any, ...]
    section_ids: frozenset[str]
    scenarios: Mapping[str, Mapping[str, Any]]
    pristine_rng_state: Mapping[str, Any]
    config_applied: Mapping[str, Any]
    pairing_rule_count: int
    _scenario_jobs: Mapping[str, tuple[Any, ...]] = field(repr=False)

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls) -> "PlanningContext":
        """Read every frozen table once. Called at startup, not per request."""
        config_applied = load_config_into_core(core, paths.CONFIG_DIR)
        rules = load_pairing_rules_into_core(core, paths.PAIRING_RULES_CSV)
        rule_count = sum(len(v) for v in rules.values())
        if rule_count == 0:
            # core.expand_mandatory_pairings would raise later anyway; failing
            # here names the real cause instead of surfacing it mid-plan.
            raise RuntimeError(
                f"no mandatory-pairing rules loaded from {paths.PAIRING_RULES_CSV}"
            )

        sections = load_sections(core, paths.SECTIONS_CSV)
        section_ids = frozenset(s.id for s in sections)

        trains = [t for t in load_trains(core, paths.MOVEMENTS_CSV)
                  if t.section_id in section_ids]

        scenario_rows = load_scenarios(paths.SCENARIOS_CSV)
        scenarios: dict[str, Mapping[str, Any]] = {}
        scenario_jobs: dict[str, tuple[Any, ...]] = {}
        for row in scenario_rows:
            name = row["scenario"]
            scenarios[name] = MappingProxyType(dict(row))
            jobs, _skipped = load_scenario_jobs(
                core, paths.DATASET_DIR, row, section_ids
            )
            scenario_jobs[name] = tuple(jobs)

        return cls(
            sections=tuple(sections),
            trains=tuple(trains),
            section_ids=section_ids,
            scenarios=MappingProxyType(scenarios),
            pristine_rng_state=MappingProxyType(
                copy.deepcopy(core.RNG.bit_generator.state)
            ),
            config_applied=MappingProxyType(dict(config_applied)),
            pairing_rule_count=rule_count,
            _scenario_jobs=MappingProxyType(scenario_jobs),
        )

    # -- accessors ---------------------------------------------------------

    @property
    def scenario_names(self) -> tuple[str, ...]:
        return tuple(self.scenarios.keys())

    def has_scenario(self, name: str) -> bool:
        return name in self.scenarios

    def scenario(self, name: str) -> Mapping[str, Any]:
        """The declared parameter row for one scenario. Raises KeyError."""
        if name not in self.scenarios:
            raise KeyError(name)
        return self.scenarios[name]

    def jobs_for(self, scenario_name: str) -> list[Any]:
        """A fresh, deep-copied job list for this scenario.

        The copy is not defensive paranoia. core.expand_mandatory_pairings()
        assigns `j.companions` on the jobs it is given, so handing out the
        stored objects would mutate the context on the first plan and break
        the "immutable after startup" guarantee. Copying ~175-340 small
        dataclasses costs microseconds.
        """
        if scenario_name not in self._scenario_jobs:
            raise KeyError(scenario_name)
        return copy.deepcopy(list(self._scenario_jobs[scenario_name]))

    def base_job_count(self, scenario_name: str) -> int:
        """Job count before pairing expansion, without copying."""
        if scenario_name not in self._scenario_jobs:
            raise KeyError(scenario_name)
        return len(self._scenario_jobs[scenario_name])

    def trains_for(self, scenario_name: str) -> list[Any]:
        """Scenario-adjusted train set.

        PEAK_TRAFFIC adds synthetic passenger paths; every other scenario uses
        the real timetable unchanged. add_peak_passenger_traffic is
        deterministic and consumes no RNG.
        """
        scenario = self.scenario(scenario_name)
        return add_peak_passenger_traffic(
            core, list(self.trains), list(self.sections), scenario
        )

    def fresh_rng_state(self, seed: int | None = None) -> dict[str, Any]:
        """A deep copy of the RNG state to reset to before a plan.

        `seed=None` (the default) returns the pristine startup state, which is
        core.RNG's state as constructed from the module's own seed. An explicit
        seed builds that seed's initial state instead, so a request can pin its
        own seed without disturbing the pristine one.
        """
        if seed is None:
            return copy.deepcopy(dict(self.pristine_rng_state))
        import numpy as np

        return copy.deepcopy(np.random.default_rng(seed).bit_generator.state)
