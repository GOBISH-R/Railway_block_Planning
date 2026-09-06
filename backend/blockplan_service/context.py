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
import csv
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


def _load_section_meta() -> Mapping[str, Mapping[str, Any]]:
    """Corridor geography per section-line, straight from the frozen CSV.

    core.Section deliberately carries only what the optimiser needs (id, line,
    is_single, headway, degraded_factor). Explaining a block to a controller
    also needs to say WHERE it is -- which two stations, how long the
    section-line is. That is in sections.csv and nowhere else, so it is read
    here rather than parsed back out of the section id string.
    """
    meta: dict[str, Mapping[str, Any]] = {}
    with open(paths.SECTIONS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            meta[row["section_id"]] = MappingProxyType({
                "section_id": row["section_id"],
                "from_station_code": row["from_station_code"],
                "to_station_code": row["to_station_code"],
                "line": row["line"],
                "length_km": float(row["length_km"]),
                "tracks": int(row["tracks"]),
                "electrified": row["electrified"] == "1",
                "is_single": row["is_single"] == "1",
                "headway_min": int(row["headway_min"]),
                "track_source": row["track_source"],
            })
    return MappingProxyType(meta)


def _load_stations() -> tuple[Mapping[str, Any], ...]:
    """The 27 real stations, in corridor sequence.

    core.py has no concept of a station -- Section carries only what the
    optimiser needs. This is presentation geography, for the /corridor
    endpoint and the frontend's linear strip diagram, read straight from the
    frozen stations.csv.
    """
    stations: list[Mapping[str, Any]] = []
    with open(paths.STATIONS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            stations.append(MappingProxyType({
                "station_code": row["station_code"],
                "station_name": row["station_name"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "seq": int(row["seq"]),
                "is_junction": row["is_junction"] == "1",
            }))
    stations.sort(key=lambda s: s["seq"])
    return tuple(stations)


def _load_pairing_rule_rows() -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    """The mandatory-pairing rules WITH their manual citations.

    core.load_pairing_rules() keeps only the five fields the optimiser uses and
    drops `source` and `confidence`. Those two are exactly what makes a
    cross-department explanation defensible -- "ACTM Ch.17 requires it" rather
    than "the system decided to" -- so the CSV is read again here for the
    citation text. The rule VALUES the optimiser uses still come solely from
    core; this is presentation metadata only.
    """
    by_activity: dict[str, list[Mapping[str, Any]]] = {}
    with open(paths.PAIRING_RULES_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_activity.setdefault(row["activity"], []).append(MappingProxyType({
                "activity": row["activity"],
                "compelled_dept": row["compelled_dept"],
                "companion_activity": row["companion_activity"],
                "duration_mean_min": float(row["duration_mean_min"]),
                "duration_sd_min": float(row["duration_sd_min"]),
                "must_follow_parent": row["must_follow_parent"] == "1",
                "precedes_parent": row["precedes_parent"] == "1",
                "source": row["source"],
                "confidence": float(row["confidence"]),
            }))
    return MappingProxyType(
        {k: tuple(v) for k, v in by_activity.items()}
    )


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
    section_meta: Mapping[str, Mapping[str, Any]]
    pairing_rules: Mapping[str, tuple[Mapping[str, Any], ...]]
    stations: tuple[Mapping[str, Any], ...]
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
            section_meta=_load_section_meta(),
            pairing_rules=_load_pairing_rule_rows(),
            stations=_load_stations(),
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
