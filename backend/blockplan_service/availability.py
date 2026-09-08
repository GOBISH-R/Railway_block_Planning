"""Asset availability: how much of the corridor's time stays open to traffic.

The problem statement asks to "maximize asset availability", and until now this
project had no metric of that name -- traffic cost was the functional proxy.
This computes the named thing.

    availability = 1 - block_minutes / capacity_minutes

DENOMINATOR: section-lines x horizon x 1440. Fifty-two section-lines, not
twenty-six station pairs, because blocking JTJ-TPT-UP does not block
JTJ-TPT-DN. Counting pairs would double every block's apparent cost and make a
double-line corridor look like a single-line one.

READ THE REST OF THIS BEFORE QUOTING THE NUMBER.

AVAILABILITY ALONE IS A TRAP, and the trap is not subtle: it is maximised by
doing no maintenance at all. A plan that defers every job scores 100%. So
AvailabilityReport carries jobs_done and jobs_deferred as required fields, and
`headline()` refuses to render the percentage without them. The claim is never
"availability is 97.8%"; it is "97.8% while completing 174 of 175 jobs".

IT ALSO CANNOT TELL 03:00 FROM 08:00. Block-minutes are block-minutes wherever
and whenever they fall, so a block on the quietest section at night counts the
same as one on the busiest at peak. Measured on the frozen benchmark: B2
Fixed-calendar ranks THIRD of six on availability while causing 743.4 weighted
delay-minutes against OURS' 299.2 -- two and a half times the disruption, from
a plan that looks competitive on this metric alone.

That is why `traffic_delay_minutes` sits beside it. It is core's own
traffic_cost: weighted train-minutes of DELAY from the queue simulator
(core.py:401). It is not turned into a second availability ratio, because the
honest denominator for that -- total weighted train-minutes of scheduled
running -- does not exist in this model. Trains are entry events with a
schedule time, not durations. Inventing a plausible-looking divisor would make
the number worse, not better, so the delay is reported in its own units and
normalised only by something genuinely countable: weighted train movements.

Nothing here touches core.py, the solver or the plan. It reads a finished plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

MINUTES_PER_DAY = 1440


@dataclass(frozen=True)
class SectionAvailability:
    """One section-line over the horizon."""

    section_id: str
    capacity_minutes: int
    block_minutes: int
    blocks: int

    @property
    def availability(self) -> float:
        if self.capacity_minutes <= 0:
            return 1.0
        return 1.0 - self.block_minutes / self.capacity_minutes

    @property
    def occupied_share(self) -> float:
        return 1.0 - self.availability


@dataclass(frozen=True)
class AvailabilityReport:
    """Corridor availability, and the work that bought it.

    jobs_done and jobs_deferred are required, not optional. A report that could
    be constructed without them would eventually be quoted without them.
    """

    horizon_days: int
    section_lines: int
    capacity_minutes: int
    block_minutes: int
    blocks: int
    jobs_done: int
    jobs_deferred: int
    traffic_delay_minutes: float
    weighted_movements: float
    by_section: Mapping[str, SectionAvailability] = field(default_factory=dict)

    @property
    def availability(self) -> float:
        """Fraction of corridor section-line time not withdrawn for maintenance."""
        if self.capacity_minutes <= 0:
            return 1.0
        return 1.0 - self.block_minutes / self.capacity_minutes

    @property
    def occupied_share(self) -> float:
        return 1.0 - self.availability

    @property
    def block_hours(self) -> float:
        return self.block_minutes / 60.0

    @property
    def delay_per_weighted_movement(self) -> float:
        """Weighted delay-minutes per weighted train movement.

        The only normalisation of the delay this model supports honestly:
        movements are countable, running time is not represented.
        """
        if self.weighted_movements <= 0:
            return 0.0
        return self.traffic_delay_minutes / self.weighted_movements

    @property
    def busiest_sections(self) -> tuple[SectionAvailability, ...]:
        """Section-lines that gave up the most time, worst first."""
        return tuple(sorted(self.by_section.values(),
                            key=lambda s: s.block_minutes, reverse=True))

    def headline(self) -> str:
        """The metric with its work figure attached. There is no other form."""
        return (f"{self.availability:.1%} corridor availability "
                f"while completing {self.jobs_done} of "
                f"{self.jobs_done + self.jobs_deferred} jobs "
                f"({self.block_hours:.1f} section-hours withdrawn, "
                f"{self.traffic_delay_minutes:.1f} weighted delay-minutes)")

    def as_dict(self) -> dict[str, Any]:
        return {
            "availability": round(self.availability, 5),
            "occupied_share": round(self.occupied_share, 5),
            "capacity_minutes": self.capacity_minutes,
            "block_minutes": self.block_minutes,
            "block_hours": round(self.block_hours, 1),
            "blocks": self.blocks,
            "section_lines": self.section_lines,
            "horizon_days": self.horizon_days,
            # Required company for the percentage; see the module docstring.
            "jobs_done": self.jobs_done,
            "jobs_deferred": self.jobs_deferred,
            "traffic_delay_minutes": round(self.traffic_delay_minutes, 1),
            # Six places, not the two or three that would look tidy: the value
            # is around 0.004, so four decimals leaves two significant figures
            # and the rounding error shows up as a visible discrepancy.
            "delay_per_weighted_movement": round(
                self.delay_per_weighted_movement, 6),
            "weighted_movements": round(self.weighted_movements, 1),
            "headline": self.headline(),
            # Per section-line, busiest first. A list rather than a map because
            # the order is the useful part: which stretches of the corridor
            # actually gave up time. Empty for reports built from the frozen
            # benchmark artefacts, which record no section breakdown.
            "by_section": [
                {
                    "section_id": s.section_id,
                    "blocks": s.blocks,
                    "block_minutes": s.block_minutes,
                    "block_hours": round(s.block_minutes / 60.0, 2),
                    "availability": round(s.availability, 5),
                }
                for s in self.busiest_sections
            ],
        }


def capacity_minutes(section_lines: int, horizon_days: int) -> int:
    """Section-line minutes available across the horizon."""
    return int(section_lines) * int(horizon_days) * MINUTES_PER_DAY


def weighted_movements(trains: Sequence[Any], horizon_days: int,
                       train_weight: Mapping[str, float]) -> float:
    """Weighted train movements over the horizon.

    Every train in this dataset carries day_mask 127 -- it runs every day -- so
    a movement recurs once per horizon day. The mask is read rather than
    assumed, so a timetable with genuine weekly variation would still count
    correctly.
    """
    total = 0.0
    for train in trains:
        mask = getattr(train, "day_mask", 127)
        days = sum(1 for day in range(int(horizon_days)) if mask >> (day % 7) & 1)
        total += train_weight.get(train.klass, 1.0) * days
    return total


def from_blocks(blocks: Sequence[Mapping[str, Any]], *, section_ids: Sequence[str],
                horizon_days: int, jobs_done: int, jobs_deferred: int,
                traffic_delay_minutes: float,
                weighted_movements_total: float = 0.0) -> AvailabilityReport:
    """Build a report from the blocks of a plan response.

    Takes the DTO's blocks rather than solver objects so this can score a
    finished plan, a restored plan, or a row set read back from the frozen
    benchmark artefacts -- all of which are the same shape.
    """
    per_section = {
        section_id: {"minutes": 0, "blocks": 0} for section_id in section_ids
    }
    total_minutes = 0
    for block in blocks:
        length = int(block["length"])
        total_minutes += length
        section_id = block["section_id"]
        bucket = per_section.setdefault(section_id, {"minutes": 0, "blocks": 0})
        bucket["minutes"] += length
        bucket["blocks"] += 1

    one_line = capacity_minutes(1, horizon_days)
    return AvailabilityReport(
        horizon_days=int(horizon_days),
        section_lines=len(per_section),
        capacity_minutes=capacity_minutes(len(per_section), horizon_days),
        block_minutes=total_minutes,
        blocks=len(blocks),
        jobs_done=int(jobs_done),
        jobs_deferred=int(jobs_deferred),
        traffic_delay_minutes=float(traffic_delay_minutes),
        weighted_movements=float(weighted_movements_total),
        by_section={
            section_id: SectionAvailability(
                section_id=section_id,
                capacity_minutes=one_line,
                block_minutes=bucket["minutes"],
                blocks=bucket["blocks"],
            )
            for section_id, bucket in per_section.items()
        },
    )


def from_frozen_artefacts(method: str | None = None
                          ) -> dict[str, AvailabilityReport]:
    """Availability of the six benchmark methods, from the frozen artefacts.

    Reads execution_scoring_blocks.csv (block lengths per method) and
    method_comparison.csv (jobs done, traffic cost). Both are frozen, and both
    rows for a method come from the SAME benchmark run, so the six are
    internally consistent and comparable with each other.

    THEY ARE NOT THE LIVE PLAN. Measured: the artefact's OURS is 115 blocks of
    150 minutes and 25 of 240 (23,250 min); the plan the app actually serves,
    2db53586d84f, is 116 and 24 (23,160 min) -- one block a different length,
    90 minutes, availability differing in the fifth decimal. Same plan id, same
    objective, same traffic cost, same block fingerprint.

    That is solver tie-breaking, documented in test_reference_plan.py: block count and
    utilisation are not determined by the model, and block LENGTH distribution
    is the same kind of quantity. It is recorded here so nobody has to explain
    on demo day why the Evidence table's OURS availability is not bit-identical
    to the live plan's. Compare the six with each other; do not mix a row from
    this file with a figure from a live solve.
    """
    import csv
    import os

    from . import paths

    lengths: dict[str, list[int]] = {}
    sections: dict[str, set[str]] = {}
    path = os.path.join(paths.SCENARIOS_DIR, "execution_scoring_blocks.csv")
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lengths.setdefault(row["method"], []).append(int(row["block_len"]))
            sections.setdefault(row["method"], set()).add(row["section_id"])

    totals: dict[str, dict[str, str]] = {}
    with open(paths.METHOD_COMPARISON_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            totals[row["method"]] = row

    reports: dict[str, AvailabilityReport] = {}
    for name, block_lengths in lengths.items():
        row = totals.get(name)
        if row is None:
            continue
        # Availability is a corridor-wide question, so the denominator is the
        # whole corridor -- not only the section-lines this method happened to
        # touch. Using the touched ones would flatter a method that concentrated
        # its work on a few sections.
        line_count = len(_frozen_section_ids())
        reports[name] = AvailabilityReport(
            horizon_days=DEFAULT_HORIZON_DAYS,
            section_lines=line_count,
            capacity_minutes=capacity_minutes(line_count, DEFAULT_HORIZON_DAYS),
            block_minutes=sum(block_lengths),
            blocks=len(block_lengths),
            jobs_done=int(row["jobs_done"]),
            jobs_deferred=int(row["jobs_deferred"]),
            traffic_delay_minutes=float(row["traffic_cost"]),
            weighted_movements=0.0,
            by_section={},
        )
    if method is not None:
        return {method: reports[method]}
    return reports


def _frozen_section_ids() -> tuple[str, ...]:
    import csv

    from . import paths

    with open(paths.SECTIONS_CSV, encoding="utf-8") as f:
        return tuple(row["section_id"] for row in csv.DictReader(f))


#: The benchmark horizon. The frozen artefacts carry no horizon column; every
#: published figure was produced at 14 days (benchmark_results.csv).
DEFAULT_HORIZON_DAYS = 14


def improvement(before: AvailabilityReport,
                after: AvailabilityReport) -> dict[str, Any]:
    """Before/after, with the work figures that stop it being read alone.

    A pure availability gain means nothing without knowing whether the same
    work got done: releasing line time by deferring jobs is not an improvement,
    it is a smaller plan.
    """
    return {
        "availability_before": round(before.availability, 5),
        "availability_after": round(after.availability, 5),
        "availability_gain": round(after.availability - before.availability, 5),
        "block_hours_before": round(before.block_hours, 1),
        "block_hours_after": round(after.block_hours, 1),
        "section_hours_released": round(before.block_hours - after.block_hours, 1),
        "jobs_done_before": before.jobs_done,
        "jobs_done_after": after.jobs_done,
        "jobs_gained": after.jobs_done - before.jobs_done,
        "traffic_delay_before": round(before.traffic_delay_minutes, 1),
        "traffic_delay_after": round(after.traffic_delay_minutes, 1),
        "headline": (
            f"{after.jobs_done - before.jobs_done:+d} jobs completed while "
            f"releasing {before.block_hours - after.block_hours:.1f} "
            f"section-hours to traffic"),
    }


def for_plan(plan: Mapping[str, Any], context: Any) -> AvailabilityReport:
    """Availability of a POST /plan response, against its own context."""
    from . import paths

    paths.ensure_import_paths()
    import core

    summary = plan["summary"]
    horizon = int(plan["horizon_days"])
    return from_blocks(
        plan["blocks"],
        section_ids=[s.id for s in context.sections],
        horizon_days=horizon,
        jobs_done=int(summary["jobs_done"]),
        jobs_deferred=int(summary["jobs_deferred"]),
        traffic_delay_minutes=float(summary["traffic_cost"]),
        weighted_movements_total=weighted_movements(
            context.trains_for(plan["scenario"]), horizon, core.TRAIN_WEIGHT),
    )
