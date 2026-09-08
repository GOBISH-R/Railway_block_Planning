"""Where a job's duration mean and sd come from.

Only the default lives here, and it lives here rather than in blockplan_ml for
one reason: importing it must not drag in LightGBM or scikit-learn. The
packaged app has to start on a machine that has never installed either, and
`python run.py` on the presentation laptop is exactly that machine.

Not pandas, though -- OR-Tools imports pandas itself, so it has been on the
default path since long before any of this. The line worth holding is the ML
libraries and blockplan_ml, and tests/test_duration_source.py checks exactly
those rather than repeating a claim about pandas that is not true.

The learned alternative is blockplan_ml.duration_source.LearnedDurations, and
planner.resolve_durations() reaches for it only when
BLOCKPLAN_DURATION_SOURCE=learned.
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

CATALOGUE = "catalogue"
LEARNED = "learned"
ENV_VAR = "BLOCKPLAN_DURATION_SOURCE"


@runtime_checkable
class DurationSource(Protocol):
    """Supplies dur_mean and dur_sd for the jobs about to be planned."""

    @property
    def name(self) -> str:
        """"catalogue" or "learned"."""

    def apply(self, jobs: Sequence[Any]) -> Sequence[Any]:
        """Set durations on these jobs, in place, and return them."""

    def describe(self) -> str:
        """One line for /health and the plan response."""


class CatalogueDurations:
    """The frozen dataset's own duration figures. The default.

    apply() is a genuine no-op, and that is the point rather than an
    optimisation. The jobs already carry these values -- load_scenario_jobs put
    them there -- so touching them at all, even a copy that round-trips through
    float(), would be a way for the default path to stop reproducing plan
    2db53586d84f. tests/test_duration_source.py asserts the objects come back
    unchanged and identical.
    """

    name = CATALOGUE

    def apply(self, jobs: Sequence[Any]) -> Sequence[Any]:
        return jobs

    def describe(self) -> str:
        return "catalogue (frozen dataset duration_mean_min / duration_sd_min)"

    def __repr__(self) -> str:
        return "CatalogueDurations()"
