"""Where a job's duration mean and sd come from. Catalogue by default.

    BLOCKPLAN_DURATION_SOURCE=catalogue   the frozen dataset's own figures (DEFAULT)
    BLOCKPLAN_DURATION_SOURCE=learned     the fitted model's estimates

CATALOGUE IS THE DEFAULT AND THE DEFAULT MUST REPRODUCE THE FROZEN PLAN. With
the flag unset, CatalogueDurations does nothing at all -- it does not copy,
round, or re-derive a single field -- so plan 2db53586d84f is bit-for-bit what
it was. tests/test_duration_source.py asserts that, and it is the gate the
whole ML track is built behind.

core.py IS NOT TOUCHED. The learned source writes two numbers onto each
core.Job before the pipeline runs:

    job.dur_mean, job.dur_sd

which is exactly what the catalogue loader already writes. core.reliability_mc
then does what it always did -- `_lognormal_params(j.dur_mean, j.dur_sd * infl)`
and samples (core.py:491) -- with no knowledge that anything changed. The
frozen sampler, the frozen solver and the frozen objective are all untouched;
only the two parameter values have a different origin.

MOMENT-MATCHING, and why it is not optional. core.py reads dur_mean and dur_sd
as the arithmetic MEAN and STANDARD DEVIATION of the duration distribution,
converts them to lognormal parameters itself, and samples. The model does not
predict a mean and an sd -- it predicts a ladder of quantiles, deliberately,
because a mean says nothing about the spread and the spread is the half that
moves the theta filter. So the ladder is matched back onto a lognormal and its
first two moments handed over. Fitting on the log scale is what makes this
consistent with the family core.py assumes rather than merely close to it.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from blockplan_service.durations import (
    CATALOGUE,
    ENV_VAR,
    LEARNED,
    CatalogueDurations,
    DurationSource,
)

from . import duration_model as dm
from . import training_table as tt

__all__ = ["CATALOGUE", "LEARNED", "ENV_VAR", "CatalogueDurations",
           "DurationSource", "LearnedDurations", "resolve", "job_frame",
           "join_reference", "lognormal_moments", "DurationSourceError"]

#: Standard-normal quantiles for the pair used to fit the log-scale spread.
#: 0.1 and 0.9 rather than the extremes: the 0.95 model is fitted on 5% of the
#: rows and is the noisiest of the six.
_Z10, _Z90 = -1.2815515655446004, 1.2815515655446004

#: A predicted sd below this is not a real estimate, it is a quantile ladder
#: that collapsed. core.py would then treat the job as effectively
#: deterministic and every bundle containing it would clear theta.
MIN_SD_MIN = 1.0


class DurationSourceError(RuntimeError):
    """The requested duration source cannot be used."""


def job_frame(jobs: Iterable[Any]) -> pd.DataFrame:
    """core.Job objects -> the serving feature frame.

    Reads only attributes core.Job actually has (core.py:92-123). dur_mean and
    dur_sd are on that object and are deliberately NOT read: they are what this
    is replacing, and they are forbidden as features.
    """
    rows = []
    for job in jobs:
        resources = getattr(job, "resources", ()) or ()
        resource_class = pd.NA
        if resources:
            resource_class = str(resources[0]).rsplit("_", 1)[0]
        rows.append({
            "job_id": job.id,
            "dept": job.dept,
            "activity": job.activity,
            "section_id": job.section_id,
            "km_from": float(job.km_from),
            "km_to": float(job.km_to),
            "km_span": float(job.km_to) - float(job.km_from),
            "needs_T": int(bool(job.needs_T)),
            "needs_P": int(bool(job.needs_P)),
            "needs_D": int(bool(job.needs_D)),
            "needs_train_movements": int(bool(job.needs_train_movements)),
            "needs_live_ohe": int(bool(job.needs_live_ohe)),
            "due_day": job.due_day,
            "criticality": job.criticality,
            "is_companion": int(getattr(job, "parent_id", None) is not None),
            "resource_class": resource_class,
        })
    return pd.DataFrame(rows)


def join_reference(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the activity, section and resource columns, exactly as training does."""
    activities = tt._read("activities.csv").add_prefix("activity_")
    sections = tt._read("sections.csv").add_prefix("section_")
    resources = tt._read("resources.csv").add_prefix("resource_")

    frame = frame.merge(activities, left_on="activity",
                        right_on="activity_activity_id", how="left")
    frame = frame.merge(sections, left_on="section_id",
                        right_on="section_section_id", how="left")
    frame = frame.merge(resources, left_on="resource_class",
                        right_on="resource_resource_class", how="left")
    return frame


def lognormal_moments(quantiles: Mapping[float, np.ndarray]) -> tuple[np.ndarray,
                                                                      np.ndarray]:
    """Quantile ladder -> (mean, sd), through a lognormal fitted on the log scale.

    sigma from the 10-90 spread, mu from the median, then the closed-form
    moments. Matching on the log scale keeps the fit inside the family core.py
    samples from, so nothing is being approximated twice.
    """
    q10 = np.asarray(quantiles[0.1], dtype=float)
    q50 = np.asarray(quantiles[0.5], dtype=float)
    q90 = np.asarray(quantiles[0.9], dtype=float)

    floor = 1e-6
    q10, q50, q90 = (np.maximum(q, floor) for q in (q10, q50, q90))

    sigma = (np.log(q90) - np.log(q10)) / (_Z90 - _Z10)
    sigma = np.clip(sigma, 1e-4, 3.0)
    mu = np.log(q50)

    mean = np.exp(mu + sigma ** 2 / 2.0)
    sd = mean * np.sqrt(np.maximum(np.exp(sigma ** 2) - 1.0, 0.0))
    return mean, np.maximum(sd, MIN_SD_MIN)


class LearnedDurations:
    """Durations from the fitted model, moment-matched onto core.py's lognormal.

    Fitted once, on construction, from the realisations it is given. ML Phase 4
    trains on 0-19 and scores on 20-29, so the training window is a parameter
    rather than a constant: a model that had seen every realisation could not be
    scored against anything.
    """

    name = LEARNED

    def __init__(self, realisations: Sequence[int] | None = None,
                 profile: str = tt.SERVING) -> None:
        self.realisations = tuple(realisations) if realisations is not None else None
        self.profile = profile
        table = tt.build(profile)
        frame = table.frame
        if self.realisations is not None:
            frame = frame[frame["realisation"].isin(self.realisations)]
            if frame.empty:
                raise DurationSourceError(
                    f"no execution rows for realisations {self.realisations}")
        self.rows_trained_on = len(frame)
        self.feature_columns = table.feature_columns
        self._model = dm.LearnedDurations(table.feature_columns).fit(
            frame, frame[tt.LABEL].to_numpy(dtype=float))

    def predict(self, jobs: Sequence[Any]) -> tuple[np.ndarray, np.ndarray]:
        features = join_reference(job_frame(jobs))
        missing = [c for c in self.feature_columns if c not in features.columns]
        if missing:
            raise DurationSourceError(
                f"the serving frame is missing {missing}; training and serving "
                "have drifted apart")
        return lognormal_moments(self._model.predict_quantiles(features))

    def apply(self, jobs: Sequence[Any]) -> Sequence[Any]:
        if not jobs:
            return jobs
        mean, sd = self.predict(jobs)
        for job, m, s in zip(jobs, mean, sd):
            job.dur_mean = float(m)
            job.dur_sd = float(s)
        return jobs

    def describe(self) -> str:
        window = ("all realisations" if self.realisations is None
                  else f"realisations {min(self.realisations)}-"
                       f"{max(self.realisations)}")
        return (f"learned (LightGBM quantiles, {window}, "
                f"{self.rows_trained_on} rows, {len(self.feature_columns)} features)")

    def __repr__(self) -> str:
        return f"LearnedDurations(realisations={self.realisations})"


def resolve(env: Mapping[str, str] | None = None) -> DurationSource:
    """Pick a duration source from the environment. Catalogue unless asked.

    An unrecognised value raises rather than falling back, for the same reason
    the data source does: silently planning with the frozen durations when
    someone asked for the model would look like it worked.
    """
    env = os.environ if env is None else env
    name = env.get(ENV_VAR, CATALOGUE).strip().lower()

    if name in ("", CATALOGUE):
        return CatalogueDurations()
    if name == LEARNED:
        window = env.get("BLOCKPLAN_DURATION_TRAIN_REALISATIONS", "").strip()
        realisations = _parse_window(window) if window else None
        return LearnedDurations(realisations)

    raise DurationSourceError(
        f"{ENV_VAR}={name!r} is not a duration source. Use {CATALOGUE!r} (the "
        f"default, the frozen figures) or {LEARNED!r}.")


def _parse_window(text: str) -> tuple[int, ...]:
    """"0-19" or "0,1,2" -> the realisations to train on."""
    text = text.strip()
    try:
        if "-" in text:
            lo, _, hi = text.partition("-")
            return tuple(range(int(lo), int(hi) + 1))
        return tuple(int(part) for part in text.split(",") if part.strip())
    except ValueError:
        raise DurationSourceError(
            f"BLOCKPLAN_DURATION_TRAIN_REALISATIONS={text!r} is not a range "
            'like "0-19" or a list like "0,1,2".') from None
