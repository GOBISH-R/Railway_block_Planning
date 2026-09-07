"""PlanningContext -- the planning inputs, read once, held immutably.

This is the layer the project memory names as the single future integration
point: today it reads a dataset tree; a division deploying this would point it
at the control office application, BDMS and the WTT, and nothing above or below
it would change.

Responsibilities (and their limits):
  - load the tables ONCE at startup, reusing the existing blockplan_adapter
    loaders rather than reimplementing CSV handling
  - hand out per-request COPIES of mutable domain objects so the context
    itself is never mutated after startup
  - remember the pristine RNG state so the planner can reset determinism

It contains no planning logic and no optimisation logic.

WHERE the tree comes from is decided above this layer, by a DataSource: the
frozen CSVs by default, or a PostgreSQL snapshot materialised to a directory.
This module takes a `DatasetTree` and cannot tell the difference -- which is
the point, and is what makes the two provably interchangeable. The tree is
carried on the context rather than read from module globals so that everything
downstream (the planner's per-solve config reload, the corridor endpoint's
movements) reads from the SAME source the context was built from. Reaching for
`paths.SECTIONS_CSV` in one of those places would silently mix a database
context with frozen files.
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

#: core.RNG's state before anything has drawn from it, captured once, here,
#: immediately after core is imported.
#:
#: This used to be read inside load(), from whatever state core.RNG happened to
#: be in at the time. That is right exactly once. core.RNG is a module global,
#: and a solve draws from it (reliability_mc, inside build_columns), so the
#: SECOND context built in a process was capturing a used stream and calling it
#: pristine. Planning twice in one process from a byte-identical dataset gave
#: 337.4 with 140 blocks, then 340.5 with 135 -- the same data, a different
#: answer. It cost a wrong conclusion once already, in Phase 3, where the
#: database was briefly blamed for it.
#:
#: In the running service there is one context, built at startup before any
#: solve, so this changes nothing there: verified equal to what the first
#: load() captured, and equal to np.random.default_rng(20260905) -- core.py's
#: own seed -- because nothing between importing core and finishing a load
#: draws from the RNG. What it fixes is every load after the first: tests, the
#: verification tool, and anything that builds a CSV context and a database
#: context side by side, which Phase 4 made possible.
_PRISTINE_RNG_STATE = copy.deepcopy(core.RNG.bit_generator.state)


def _load_section_meta(tree: paths.DatasetTree) -> Mapping[str, Mapping[str, Any]]:
    """Corridor geography per section-line, straight from the CSV.

    core.Section deliberately carries only what the optimiser needs (id, line,
    is_single, headway, degraded_factor). Explaining a block to a controller
    also needs to say WHERE it is -- which two stations, how long the
    section-line is. That is in sections.csv and nowhere else, so it is read
    here rather than parsed back out of the section id string.
    """
    meta: dict[str, Mapping[str, Any]] = {}
    with open(tree.sections_csv, encoding="utf-8") as f:
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


def _load_stations(tree: paths.DatasetTree) -> tuple[Mapping[str, Any], ...]:
    """The 27 real stations, in corridor sequence.

    core.py has no concept of a station -- Section carries only what the
    optimiser needs. This is presentation geography, for the /corridor
    endpoint and the frontend's linear strip diagram, read straight from the
    frozen stations.csv.
    """
    stations: list[Mapping[str, Any]] = []
    with open(tree.stations_csv, encoding="utf-8") as f:
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


def _load_pairing_rule_rows(tree: paths.DatasetTree) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    """The mandatory-pairing rules WITH their manual citations.

    core.load_pairing_rules() keeps only the five fields the optimiser uses and
    drops `source` and `confidence`. Those two are exactly what makes a
    cross-department explanation defensible -- "ACTM Ch.17 requires it" rather
    than "the system decided to" -- so the CSV is read again here for the
    citation text. The rule VALUES the optimiser uses still come solely from
    core; this is presentation metadata only.
    """
    by_activity: dict[str, list[Mapping[str, Any]]] = {}
    with open(tree.pairing_rules_csv, encoding="utf-8") as f:
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
    """Immutable snapshot of one dataset.

    Mutable domain objects (`core.Job`) are never handed out directly -- see
    `jobs_for()`. `core.Section`, `core.Train` and `core.Window` are all
    frozen dataclasses and are safe to share.
    """

    tree: paths.DatasetTree
    source_description: str
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

    # The DataSource the tree came from, held for its LIFETIME, not for use.
    # A DatabaseDataSource owns a TemporaryDirectory, and dropping the last
    # reference to it lets the finaliser delete the materialised tree while
    # this context is still pointing at it. Startup would survive that --
    # sections, trains and jobs are already in memory -- and then the first
    # lazily-read file would fail: /demand and /corridor read their CSVs per
    # request. Found exactly that way, by driving the real API in both modes.
    _source: Any = field(default=None, repr=False, compare=False)

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls, source: Any = None) -> "PlanningContext":
        """Read every table once. Called at startup, not per request.

        `source` is a DataSource (datasource.py). Omitted, it resolves from the
        environment, which defaults to the frozen CSVs -- so `load()` with no
        argument behaves exactly as it always has, and every existing caller
        and test keeps its meaning.

        A `DatasetTree` is also accepted directly, for tools that already know
        which tree they want.
        """
        if source is None:
            from .datasource import resolve

            source = resolve()

        if isinstance(source, paths.DatasetTree):
            tree, description, owner = source, f"dataset tree at {source.root}", None
        else:
            tree, description, owner = source.open(), source.describe(), source

        config_applied = load_config_into_core(core, paths.CONFIG_DIR)
        rules = load_pairing_rules_into_core(core, tree.pairing_rules_csv)
        rule_count = sum(len(v) for v in rules.values())
        if rule_count == 0:
            # core.expand_mandatory_pairings would raise later anyway; failing
            # here names the real cause instead of surfacing it mid-plan.
            raise RuntimeError(
                f"no mandatory-pairing rules loaded from {tree.pairing_rules_csv}"
            )

        sections = load_sections(core, tree.sections_csv)
        section_ids = frozenset(s.id for s in sections)

        trains = [t for t in load_trains(core, tree.movements_csv)
                  if t.section_id in section_ids]

        scenario_rows = load_scenarios(tree.scenarios_csv)
        scenarios: dict[str, Mapping[str, Any]] = {}
        scenario_jobs: dict[str, tuple[Any, ...]] = {}
        for row in scenario_rows:
            name = row["scenario"]
            scenarios[name] = MappingProxyType(dict(row))
            jobs, _skipped = load_scenario_jobs(
                core, tree.root, row, section_ids
            )
            scenario_jobs[name] = tuple(jobs)

        return cls(
            tree=tree,
            source_description=description,
            _source=owner,
            sections=tuple(sections),
            trains=tuple(trains),
            section_ids=section_ids,
            scenarios=MappingProxyType(scenarios),
            pristine_rng_state=MappingProxyType(
                copy.deepcopy(_PRISTINE_RNG_STATE)
            ),
            config_applied=MappingProxyType(dict(config_applied)),
            pairing_rule_count=rule_count,
            section_meta=_load_section_meta(tree),
            pairing_rules=_load_pairing_rule_rows(tree),
            stations=_load_stations(tree),
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
