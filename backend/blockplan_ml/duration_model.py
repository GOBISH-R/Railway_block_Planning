"""Learned duration distributions, and an honest account of what they can do.

Three predictors, evaluated side by side because the comparison is the result:

    ORACLE      predicts each job's own duration_mean_min. Uses a FORBIDDEN
                column and is never a feature source -- it exists to show the
                ceiling under perfect knowledge of the generating parameter.
    BASELINE    the per-activity mean of observed durations. A lookup.
    LEARNED     LightGBM over the 61 legal features.

WHAT THE COMPARISON WILL SHOW, and why it is worth stating before running it
rather than after. From dsgen/demand.py:152-154 a job's parameters are drawn
from the activity catalogue and nothing else:

    mean = trunc_lognormal(catalogue_mean, catalogue_sd * 0.5, ...)
    sd   = catalogue_sd * uncertainty_scale * uniform(0.8, 1.25)

Section, km span, protection, resource class, criticality and due day never
enter the duration path. So conditional on `activity`, the label is independent
of every other legal feature, and the per-activity mean is not a baseline to
beat -- it is the Bayes-optimal predictor over the legal feature set. LEARNED
matching BASELINE is the correct outcome. LEARNED beating it by a margin would
be a symptom, not an achievement.

The models are still worth building and are used in ML Phase 4, where the
question is not accuracy but what a different duration estimate does to the
plan. But nothing here should be presented as a predictive win.

QUANTILES, NOT A POINT. core.py samples a lognormal per job when it estimates
block reliability. A learned model that only produced a mean would say nothing
about spread, which is the half that actually moves the theta filter. So the
distribution is estimated directly by quantile regression at six levels, with
no distributional assumption, and moment-matched back onto core.py's lognormal
at the point of use (ML Phase 3).
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from . import training_table as tt

QUANTILES = (0.1, 0.25, 0.5, 0.75, 0.9, 0.95)

#: core.ALLOWED_BLOCK_LENGTHS. An overrun is work still in progress when the
#: block ends, so the classifier is trained per candidate length.
BLOCK_LENGTHS = (150, 240)

#: Deliberately small. 238 jobs x 30 realisations is not much data, the signal
#: is one categorical, and a deep forest here would fit realisation noise.
LGBM_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 40,
    "verbose": -1,
    "deterministic": True,
    "force_row_wise": True,
    "seed": 20260908,
}


# -- preparation -------------------------------------------------------------

def prepare(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """Feature frame LightGBM can consume: object columns become categories."""
    features = frame[list(columns)].copy()
    for column in features.columns:
        if features[column].dtype == object or isinstance(
                features[column].dtype, pd.StringDtype):
            features[column] = features[column].astype("category")
        elif features[column].dtype == "boolean":
            features[column] = features[column].astype("float64")
    return features


def _numeric(series: pd.Series) -> np.ndarray:
    return pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)


# -- metrics -----------------------------------------------------------------

def r2(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    ss_res = float(np.sum((actual - predicted) ** 2))
    ss_tot = float(np.sum((actual - actual.mean()) ** 2))
    return 1.0 - ss_res / ss_tot


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(actual, float)
                                - np.asarray(predicted, float))))


def pinball(actual: np.ndarray, predicted: np.ndarray, tau: float) -> float:
    """Quantile loss. The proper scoring rule for a quantile forecast."""
    delta = np.asarray(actual, float) - np.asarray(predicted, float)
    return float(np.mean(np.maximum(tau * delta, (tau - 1.0) * delta)))


def coverage(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Fraction of outcomes at or below the predicted quantile."""
    return float(np.mean(np.asarray(actual, float)
                         <= np.asarray(predicted, float)))


def pit(actual: np.ndarray, quantile_predictions: dict[float, np.ndarray]) -> np.ndarray:
    """Probability integral transform, from the predicted quantile ladder.

    Each outcome is placed in the predicted distribution by counting how many
    predicted quantiles it exceeds. Uniform means calibrated; a U shape means
    over-confident, a hump means under-confident.
    """
    taus = sorted(quantile_predictions)
    ladder = np.column_stack([quantile_predictions[t] for t in taus])
    actual = np.asarray(actual, float)[:, None]
    below = (actual > ladder).sum(axis=1)
    edges = np.array([0.0, *taus, 1.0])
    return (edges[below] + edges[below + 1]) / 2.0


# -- predictors --------------------------------------------------------------

class ActivityMean:
    """The baseline, and -- see the module docstring -- the optimal predictor.

    Falls back to the global mean for an activity never seen in training, which
    is what makes the activity-holdout split fail rather than crash.
    """

    name = "baseline (activity mean)"

    def __init__(self) -> None:
        self._by_activity: dict[str, float] = {}
        self._quantiles: dict[str, dict[float, float]] = {}
        self._global = 0.0
        self._global_quantiles: dict[float, float] = {}

    def fit(self, frame: pd.DataFrame, label: np.ndarray) -> "ActivityMean":
        work = pd.DataFrame({"activity": frame["activity"].to_numpy(), "y": label})
        self._global = float(work["y"].mean())
        self._global_quantiles = {t: float(work["y"].quantile(t)) for t in QUANTILES}
        for activity, group in work.groupby("activity", observed=True):
            self._by_activity[activity] = float(group["y"].mean())
            self._quantiles[activity] = {
                t: float(group["y"].quantile(t)) for t in QUANTILES}
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.array([self._by_activity.get(a, self._global)
                         for a in frame["activity"]], dtype=float)

    def predict_quantiles(self, frame: pd.DataFrame) -> dict[float, np.ndarray]:
        return {
            t: np.array([self._quantiles.get(a, self._global_quantiles)[t]
                         for a in frame["activity"]], dtype=float)
            for t in QUANTILES
        }

    def unseen_activities(self, frame: pd.DataFrame) -> int:
        return int(sum(a not in self._by_activity for a in frame["activity"]))


class LearnedDurations:
    """LightGBM: one L2 model for the point estimate, one per quantile."""

    name = "learned (LightGBM)"

    def __init__(self, columns: Sequence[str], params: dict[str, Any] | None = None):
        self.columns = tuple(columns)
        self.params = dict(params or LGBM_PARAMS)
        self._mean: Any = None
        self._quantile: dict[float, Any] = {}

    def fit(self, frame: pd.DataFrame, label: np.ndarray) -> "LearnedDurations":
        import lightgbm as lgb

        features = prepare(frame, self.columns)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._mean = lgb.LGBMRegressor(objective="l2", **self.params)
            self._mean.fit(features, label)
            for tau in QUANTILES:
                model = lgb.LGBMRegressor(objective="quantile", alpha=tau,
                                          **self.params)
                model.fit(features, label)
                self._quantile[tau] = model
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.asarray(self._mean.predict(prepare(frame, self.columns)), dtype=float)

    def predict_quantiles(self, frame: pd.DataFrame) -> dict[float, np.ndarray]:
        features = prepare(frame, self.columns)
        raw = {t: np.asarray(m.predict(features), float)
               for t, m in self._quantile.items()}
        # Quantile models are fitted independently and can cross. Sorting each
        # row restores monotonicity, which every downstream use assumes.
        ladder = np.sort(np.column_stack([raw[t] for t in QUANTILES]), axis=1)
        return {t: ladder[:, i] for i, t in enumerate(QUANTILES)}


class OverrunRisk:
    """P(work outruns the block), isotonic-calibrated, one model per length.

    A raw classifier score is not a probability. core.py's theta constraint is
    a probability statement, so anything feeding it has to be calibrated or the
    constraint means something other than it says.
    """

    def __init__(self, columns: Sequence[str],
                 lengths: Sequence[int] = BLOCK_LENGTHS):
        self.columns = tuple(columns)
        self.lengths = tuple(lengths)
        self._models: dict[int, Any] = {}
        self._degenerate: dict[int, float] = {}

    def fit(self, frame: pd.DataFrame, label: np.ndarray) -> "OverrunRisk":
        import lightgbm as lgb
        from sklearn.calibration import CalibratedClassifierCV

        features = prepare(frame, self.columns)
        for length in self.lengths:
            overran = (np.asarray(label, float) > length).astype(int)
            # A length no job ever exceeds has no classifier to fit; record the
            # constant rather than fabricating a model.
            if overran.min() == overran.max():
                self._degenerate[length] = float(overran.mean())
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                base = lgb.LGBMClassifier(**self.params_for(length))
                model = CalibratedClassifierCV(base, method="isotonic", cv=3)
                model.fit(features, overran)
            self._models[length] = model
        return self

    def params_for(self, length: int) -> dict[str, Any]:
        return dict(LGBM_PARAMS)

    def predict(self, frame: pd.DataFrame, length: int) -> np.ndarray:
        if length in self._degenerate:
            return np.full(len(frame), self._degenerate[length], dtype=float)
        model = self._models[length]
        return np.asarray(
            model.predict_proba(prepare(frame, self.columns))[:, 1], dtype=float)


# -- evaluation --------------------------------------------------------------

@dataclass(frozen=True)
class Score:
    predictor: str
    r2: float
    mae: float
    pinball: dict[float, float] = field(default_factory=dict)
    coverage: dict[float, float] = field(default_factory=dict)
    note: str = ""


@dataclass(frozen=True)
class SplitResult:
    split: str
    question: str
    train_rows: int
    test_rows: int
    scores: tuple[Score, ...]
    pit_values: dict[str, np.ndarray] = field(default_factory=dict)


def _score(name: str, actual: np.ndarray, point: np.ndarray,
           quantiles: dict[float, np.ndarray], note: str = "") -> Score:
    return Score(
        predictor=name,
        r2=r2(actual, point),
        mae=mae(actual, point),
        pinball={t: pinball(actual, q, t) for t, q in sorted(quantiles.items())},
        coverage={t: coverage(actual, q) for t, q in sorted(quantiles.items())},
        note=note,
    )


def evaluate_split(table: tt.TrainingTable, train_index, test_index,
                   split: str, question: str) -> SplitResult:
    frame = table.frame
    train, test = frame.iloc[train_index], frame.iloc[test_index]
    y_train = train[tt.LABEL].to_numpy(dtype=float)
    y_test = test[tt.LABEL].to_numpy(dtype=float)

    scores: list[Score] = []
    pits: dict[str, np.ndarray] = {}

    # ORACLE -- uses the label's own generating parameter. Reference only.
    #
    # Scored on the base jobs alone, because companions have no row in
    # jobs.csv and so no duration_mean_min to read; their parameters live in
    # pairing_rules.csv. Restricting to where the parameter exists is honest;
    # dropping the oracle entirely would lose the one number that says how much
    # of the residual is irreducible.
    if "duration_mean_min" in test:
        oracle = _numeric(test["duration_mean_min"])
        known = np.isfinite(oracle)
        if known.any():
            scores.append(Score(
                predictor="oracle (true duration_mean_min)",
                r2=r2(y_test[known], oracle[known]),
                mae=mae(y_test[known], oracle[known]),
                note=f"FORBIDDEN as a feature; ceiling under perfect knowledge, "
                     f"on the {int(known.sum())} base-job rows only"))

    baseline = ActivityMean().fit(train, y_train)
    b_point = baseline.predict(test)
    b_quantiles = baseline.predict_quantiles(test)
    unseen = baseline.unseen_activities(test)
    scores.append(_score(
        baseline.name, y_test, b_point, b_quantiles,
        note=f"{unseen} test rows had an activity absent from training"
        if unseen else ""))
    pits[baseline.name] = pit(y_test, b_quantiles)

    learned = LearnedDurations(table.feature_columns).fit(train, y_train)
    l_point = learned.predict(test)
    l_quantiles = learned.predict_quantiles(test)
    scores.append(_score(learned.name, y_test, l_point, l_quantiles))
    pits[learned.name] = pit(y_test, l_quantiles)

    return SplitResult(split, question, len(train), len(test),
                       tuple(scores), pits)


def realisation_holdout(table: tt.TrainingTable, cut: int = 20) -> SplitResult:
    """Train on realisations 0..cut-1, test on the rest. Same jobs throughout."""
    realisation = table.frame["realisation"].to_numpy()
    return evaluate_split(
        table, np.flatnonzero(realisation < cut), np.flatnonzero(realisation >= cut),
        f"realisation-holdout (0-{cut - 1} / {cut}-29)",
        "predicts future executions of jobs already seen?")


def job_holdout(table: tt.TrainingTable, folds: int = 5) -> list[SplitResult]:
    """GroupKFold on job_id: every fold's test jobs are unseen in training.

    The honest split. A request arriving tomorrow is a job the model has never
    executed, so this is the only one that answers the operational question.
    """
    from sklearn.model_selection import GroupKFold

    groups = table.frame["job_id"].to_numpy()
    splitter = GroupKFold(n_splits=folds)
    out = []
    for n, (train_index, test_index) in enumerate(
            splitter.split(table.frame, groups=groups), start=1):
        out.append(evaluate_split(
            table, train_index, test_index, f"job-holdout fold {n}/{folds}",
            "generalises to a job never executed before?"))
    return out


def activity_holdout(table: tt.TrainingTable,
                     held_out: Iterable[str] | None = None) -> SplitResult:
    """Hold out whole activities. Expected to fail, and reported as such.

    Since the label depends on the activity and nothing else, an activity with
    no training rows has no recoverable mean. Failure here is the measurement
    confirming that, not a defect to tune away.
    """
    frame = table.frame
    if held_out is None:
        counts = frame.loc[frame["is_companion"] == 0, "activity"].value_counts()
        held_out = list(counts.index[len(counts) // 2:][:3])
    held_out = list(held_out)
    mask = frame["activity"].isin(held_out).to_numpy()
    return evaluate_split(
        table, np.flatnonzero(~mask), np.flatnonzero(mask),
        f"activity-holdout ({', '.join(held_out)})",
        "generalises to a kind of work never seen? (expected: no)")
