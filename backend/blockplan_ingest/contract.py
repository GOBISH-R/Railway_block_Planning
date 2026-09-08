"""The ingestion contract: what a maintenance-management feed must supply.

The problem statement names TMS, SMMS and TDMS as the systems this tool would
draw its maintenance demand from, and they map cleanly onto the three
departments this project already plans for:

    TMS   Track Management System        -> ENGG   (TRACK_KM, TURNOUT)
    SMMS  Signal Maintenance Mgmt System -> SNT    (SIGNAL_POINT, TURNOUT)
    TDMS  Traction Distribution Mgmt Sys -> TRD    (OHE_KM, TRACK_KM)

WHAT THIS FILE IS NOT.

It is NOT a reproduction of any real system's schema. We do not have the TMS,
SMMS or TDMS interface specifications, and inventing field names and then
labelling them "the TMS schema" would be a fabrication of exactly the kind
is forbidden -- the same rule that stops this project describing
its synthetic maintenance jobs as real Indian Railways operational data.

What it IS: the contract THIS system accepts, defined by what the planner
provably needs, with every field traced to the core.Job attribute it feeds. An
integrator connecting a real TMS writes a mapping onto this contract. That
mapping is their work and it is small -- the fields below are the irreducible
set, and `REQUIRED_TO_PLAN` says exactly which of them cannot be defaulted.

Asked "is this the real TMS schema?", the answer is no, and the answer to
"what would it take to connect the real one?" is this file plus a field
mapping. That is an honest position to defend; a fabricated schema is not.

PROVENANCE. Every record carries `source_system` and every job built from one
carries it through, so a plan can always say which system asked for the work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

TMS = "TMS"
SMMS = "SMMS"
TDMS = "TDMS"

#: source system -> the department whose work it raises.
DEPARTMENT_OF = {TMS: "ENGG", SMMS: "SNT", TDMS: "TRD"}

#: The reverse, for building a feed out of an existing job set.
SYSTEM_OF = {dept: system for system, dept in DEPARTMENT_OF.items()}

SOURCE_SYSTEMS = tuple(DEPARTMENT_OF)


class ContractError(ValueError):
    """A feed record cannot be accepted, and silently dropping it would be worse."""


@dataclass(frozen=True)
class MaintenanceDemand:
    """One piece of work a source system says is due.

    Every field below exists because core.Job needs it (core.py:92-123), not
    because a real system happens to publish it. The mapping is one to one:

        work_order_id     -> Job.id
        source_system     -> provenance only; never reaches the optimiser
        activity_code     -> Job.activity, and the catalogue lookup for
                             protection, duration and asset class
        section_id        -> Job.section_id
        km_from / km_to   -> Job.km_from / Job.km_to  (the work's footprint)
        due_day           -> Job.due_day
        criticality       -> Job.criticality
        duration_mean_min -> Job.dur_mean
        duration_sd_min   -> Job.dur_sd

    A real feed will publish a due DATE, not a day index, and an asset
    location, not a kilometre pair. Converting those is the integrator's
    mapping, and it is deliberately not hidden inside this contract: a date
    needs a planning epoch to become an index, and guessing the epoch is how
    an integration silently plans the wrong fortnight.
    """

    work_order_id: str
    source_system: str
    activity_code: str
    section_id: str
    km_from: float
    km_to: float
    due_day: int
    criticality: float
    duration_mean_min: float
    duration_sd_min: float
    #: Which machine or gang is allocated, e.g. "TAMPER_3". OPTIONAL, and the
    #: consequence of omitting it is not neutral: core.py:287 refuses to bundle
    #: two jobs that share a resource, so without an allocation every job of a
    #: class collapses onto one instance and the planner assumes maximum fleet
    #: contention. That is the conservative direction -- it produces more blocks,
    #: never fewer -- but it is an assumption, and validate() counts how many
    #: records relied on it so it cannot pass unnoticed.
    resource_id: str | None = None
    #: Anything the source system publishes that this planner does not consume.
    #: Carried so an integrator can round-trip their own identifiers without
    #: this contract having to know about them.
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def dept(self) -> str:
        return DEPARTMENT_OF[self.source_system]


#: Fields with no defensible default. A feed missing any of these is rejected
#: rather than completed with a guess: core.Job itself refuses a job with a
#: missing duration, due day or criticality (core.py:108-116, __post_init__),
#: and a silently substituted value would enter bundles, reliability draws and
#: the objective looking entirely plausible.
REQUIRED_TO_PLAN = (
    "work_order_id", "source_system", "activity_code", "section_id",
    "km_from", "km_to", "due_day", "criticality",
    "duration_mean_min", "duration_sd_min",
)


def _number(record: Mapping[str, Any], key: str, work_order: str) -> float:
    value = record.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ContractError(
            f"{work_order}: {key}={value!r} is not a number") from None


def parse_demand(record: Mapping[str, Any]) -> MaintenanceDemand:
    """One feed record -> one MaintenanceDemand, or a clear refusal."""
    work_order = str(record.get("work_order_id", "<no work_order_id>"))

    missing = [f for f in REQUIRED_TO_PLAN
               if record.get(f) is None or record.get(f) == ""]
    if missing:
        raise ContractError(
            f"{work_order}: missing required field(s) {missing}. These have no "
            "defensible default -- core.Job rejects a job without a duration, "
            "due day or criticality, and substituting one would produce a "
            "plausible-looking job that enters the objective unnoticed.")

    system = str(record["source_system"]).strip().upper()
    if system not in DEPARTMENT_OF:
        raise ContractError(
            f"{work_order}: source_system={system!r} is not one of "
            f"{', '.join(SOURCE_SYSTEMS)}.")

    km_from = _number(record, "km_from", work_order)
    km_to = _number(record, "km_to", work_order)
    if km_to <= km_from:
        raise ContractError(
            f"{work_order}: km_to ({km_to}) must exceed km_from ({km_from}); a "
            "zero-length footprint cannot overlap-check against other work.")

    duration_mean = _number(record, "duration_mean_min", work_order)
    duration_sd = _number(record, "duration_sd_min", work_order)
    if duration_mean <= 0:
        raise ContractError(
            f"{work_order}: duration_mean_min must be positive, got {duration_mean}")
    if duration_sd < 0:
        raise ContractError(
            f"{work_order}: duration_sd_min cannot be negative, got {duration_sd}")

    known = set(REQUIRED_TO_PLAN) | {"resource_id"}
    return MaintenanceDemand(
        work_order_id=work_order,
        source_system=system,
        activity_code=str(record["activity_code"]).strip(),
        section_id=str(record["section_id"]).strip(),
        km_from=km_from,
        km_to=km_to,
        due_day=int(_number(record, "due_day", work_order)),
        criticality=_number(record, "criticality", work_order),
        duration_mean_min=duration_mean,
        duration_sd_min=duration_sd,
        resource_id=(str(record["resource_id"]).strip()
                     if record.get("resource_id") else None),
        extra={k: v for k, v in record.items() if k not in known},
    )


@dataclass(frozen=True)
class FeedValidation:
    """What a feed contained, and what could not be used.

    Rejections are returned rather than raised so one bad work order does not
    discard an otherwise usable feed -- but they are never discarded silently:
    the caller gets them and decides.
    """

    accepted: tuple[MaintenanceDemand, ...]
    rejected: tuple[tuple[str, str], ...]      # (work_order_id, reason)

    @property
    def ok(self) -> bool:
        return not self.rejected

    @property
    def without_resource_allocation(self) -> tuple[str, ...]:
        """Work orders that named no machine or gang.

        Each of these will be planned as though it contends with every other
        job of its class. Reported rather than silently defaulted -- see
        MaintenanceDemand.resource_id.
        """
        return tuple(d.work_order_id for d in self.accepted if not d.resource_id)

    def by_system(self) -> dict[str, tuple[MaintenanceDemand, ...]]:
        out: dict[str, list[MaintenanceDemand]] = {s: [] for s in SOURCE_SYSTEMS}
        for demand in self.accepted:
            out[demand.source_system].append(demand)
        return {system: tuple(items) for system, items in out.items()}

    def summary(self) -> str:
        counts = {s: len(v) for s, v in self.by_system().items() if v}
        detail = ", ".join(f"{s} {n}" for s, n in sorted(counts.items()))
        rejected = f", {len(self.rejected)} rejected" if self.rejected else ""
        unallocated = self.without_resource_allocation
        note = (f", {len(unallocated)} with no resource allocation"
                if unallocated else "")
        return f"{len(self.accepted)} work orders ({detail}){rejected}{note}"


def validate(records: Iterable[Mapping[str, Any]],
             *, known_sections: Sequence[str] | None = None,
             known_activities: Sequence[str] | None = None) -> FeedValidation:
    """Parse a feed, keeping what is usable and naming what is not.

    `known_sections` and `known_activities` are checked when supplied. A work
    order for a section this corridor does not have, or an activity the
    catalogue does not define, cannot be planned -- and would otherwise fail
    much later, inside window generation, with an error naming neither the feed
    nor the record.
    """
    sections = set(known_sections) if known_sections is not None else None
    activities = set(known_activities) if known_activities is not None else None

    accepted: list[MaintenanceDemand] = []
    rejected: list[tuple[str, str]] = []
    seen: set[str] = set()

    for record in records:
        work_order = str(record.get("work_order_id", "<no work_order_id>"))
        try:
            demand = parse_demand(record)
        except ContractError as exc:
            rejected.append((work_order, str(exc)))
            continue

        if demand.work_order_id in seen:
            rejected.append((demand.work_order_id,
                             "duplicate work_order_id in this feed"))
            continue
        if sections is not None and demand.section_id not in sections:
            rejected.append((demand.work_order_id,
                             f"section {demand.section_id!r} is not on this corridor"))
            continue
        if activities is not None and demand.activity_code not in activities:
            rejected.append((demand.work_order_id,
                             f"activity {demand.activity_code!r} is not in the "
                             "catalogue, so its protection regime is unknown"))
            continue

        seen.add(demand.work_order_id)
        accepted.append(demand)

    return FeedValidation(tuple(accepted), tuple(rejected))
