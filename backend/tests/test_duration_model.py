"""The duration model: the metrics are right and the model sees nothing it shouldn't.

Deliberately not a test of accuracy. Accuracy is measured in the evaluation
report and depends on a split; pinning a number here would either be a
tautology or a tripwire that fires on a LightGBM point release.

What is pinned is the machinery: that a quantile ladder cannot cross, that an
unseen activity falls back rather than crashes, that a probability is a
probability, and above all that no forbidden column reaches a fitted model.
The last one is the whole argument for the result being meaningful at all.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from blockplan_ml import duration_model as dm
from blockplan_ml import training_table as tt


@pytest.fixture(scope="module")
def table() -> tt.TrainingTable:
    return tt.build()


@pytest.fixture(scope="module")
def small(table: tt.TrainingTable) -> tt.TrainingTable:
    """Six realisations. Enough to fit, quick enough to fit repeatedly."""
    frame = table.frame[table.frame["realisation"] < 6].reset_index(drop=True)
    return tt.TrainingTable(frame, table.feature_columns, table.profile)


# -- metrics ----------------------------------------------------------------

def test_r2_is_one_for_a_perfect_prediction():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert dm.r2(y, y) == pytest.approx(1.0)


def test_r2_is_zero_for_predicting_the_mean():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert dm.r2(y, np.full_like(y, y.mean())) == pytest.approx(0.0)


def test_r2_goes_negative_when_worse_than_the_mean():
    """The activity-holdout split reports a negative R2 and that is a real
    result, not a bug -- so the metric has to be able to express it."""
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert dm.r2(y, np.full_like(y, 100.0)) < 0


def test_pinball_penalises_the_two_sides_asymmetrically():
    """A 0.9 quantile should be punished far more for being too low than too
    high; that asymmetry is the entire point of the loss."""
    y = np.array([10.0])
    too_low = dm.pinball(y, np.array([0.0]), 0.9)
    too_high = dm.pinball(y, np.array([20.0]), 0.9)
    assert too_low > too_high
    assert dm.pinball(y, np.array([0.0]), 0.5) == pytest.approx(
        dm.pinball(y, np.array([20.0]), 0.5))


def test_coverage_counts_outcomes_at_or_below_the_quantile():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert dm.coverage(y, np.array([2.0, 2.0, 2.0, 2.0])) == pytest.approx(0.5)


def test_pit_places_an_outcome_in_the_right_interval():
    """Below every predicted quantile -> the lowest interval; above them all ->
    the highest."""
    ladder = {t: np.array([10.0 * (i + 1)]) for i, t in enumerate(dm.QUANTILES)}
    assert dm.pit(np.array([0.0]), ladder)[0] < 0.1
    assert dm.pit(np.array([1000.0]), ladder)[0] > 0.95


# -- the baseline -----------------------------------------------------------

def test_the_baseline_predicts_the_mean_of_each_activity(small):
    model = dm.ActivityMean().fit(small.frame, small.labels().to_numpy(float))
    predicted = model.predict(small.frame)
    observed = small.frame.groupby("activity", observed=True)[tt.LABEL].mean()
    for activity, value in observed.items():
        rows = (small.frame["activity"] == activity).to_numpy()
        assert predicted[rows] == pytest.approx(value)


def test_the_baseline_falls_back_for_an_activity_it_never_saw(small):
    """This is what makes activity-holdout a measurement rather than a crash.
    The fallback is the global mean, and it is why that split scores below
    zero."""
    frame = small.frame
    held = frame["activity"].iloc[0]
    train = frame[frame["activity"] != held]
    test = frame[frame["activity"] == held]

    model = dm.ActivityMean().fit(train, train[tt.LABEL].to_numpy(float))
    assert model.unseen_activities(test) == len(test)
    predicted = model.predict(test)
    assert np.allclose(predicted, predicted[0]), "fallback must be one constant"
    assert np.isfinite(predicted).all()


def test_the_baseline_quantiles_are_ordered(small):
    model = dm.ActivityMean().fit(small.frame, small.labels().to_numpy(float))
    ladder = model.predict_quantiles(small.frame)
    values = np.column_stack([ladder[t] for t in dm.QUANTILES])
    assert (np.diff(values, axis=1) >= 0).all()


# -- the learned model ------------------------------------------------------

@pytest.mark.slow
def test_the_learned_quantile_ladder_never_crosses(small):
    """Quantile models are fitted independently, so nothing stops the 0.25
    model predicting above the 0.75 model on a given row. Downstream code
    assumes an ordered ladder, so predict_quantiles sorts each row -- and this
    is what checks that it does."""
    model = dm.LearnedDurations(small.feature_columns).fit(
        small.frame, small.labels().to_numpy(float))
    ladder = model.predict_quantiles(small.frame)
    values = np.column_stack([ladder[t] for t in dm.QUANTILES])
    assert (np.diff(values, axis=1) >= -1e-9).all()
    assert np.isfinite(values).all()


@pytest.mark.slow
def test_the_learned_model_produces_usable_durations(small):
    model = dm.LearnedDurations(small.feature_columns).fit(
        small.frame, small.labels().to_numpy(float))
    predicted = model.predict(small.frame)
    assert np.isfinite(predicted).all()
    assert (predicted > 0).all(), "a negative duration is not a duration"


# -- the guard, at the point of use -----------------------------------------

def test_no_forbidden_column_reaches_the_feature_frame(table):
    """The table-level guard is tested elsewhere. This checks the frame that is
    actually handed to LightGBM, which is where it would matter."""
    prepared = dm.prepare(table.frame, table.feature_columns)
    bare = {tt._bare(c) for c in prepared.columns}
    assert tt.FORBIDDEN.isdisjoint(bare)
    assert tt.IDENTIFIERS.isdisjoint(set(prepared.columns))


def test_the_oracle_is_not_reachable_as_a_feature(table):
    """The oracle reads duration_mean_min and is reported as a ceiling. It must
    remain impossible to reach that column through the feature path."""
    assert "duration_mean_min" in table.frame.columns, "the oracle needs it"
    assert "duration_mean_min" not in table.feature_columns


def test_prepare_makes_text_columns_categorical(table):
    prepared = dm.prepare(table.frame, table.feature_columns)
    assert not any(prepared[c].dtype == object for c in prepared.columns)


# -- overrun risk -----------------------------------------------------------

@pytest.mark.slow
def test_overrun_risk_returns_probabilities(small):
    model = dm.OverrunRisk(small.feature_columns).fit(
        small.frame, small.labels().to_numpy(float))
    for length in dm.BLOCK_LENGTHS:
        p = model.predict(small.frame, length)
        assert len(p) == len(small.frame)
        assert ((p >= 0.0) & (p <= 1.0)).all(), f"length {length} left [0,1]"


@pytest.mark.slow
def test_a_block_length_nothing_overruns_is_reported_as_a_constant(small):
    """The longest allowed block is 240 minutes and the longest observed job is
    under 300, so at some lengths the label has one class. Fitting a classifier
    on one class is not possible; recording the constant is honest, inventing a
    model is not."""
    model = dm.OverrunRisk(small.feature_columns, lengths=(10_000,)).fit(
        small.frame, small.labels().to_numpy(float))
    p = model.predict(small.frame, 10_000)
    assert (p == 0.0).all()


def test_the_block_lengths_match_the_frozen_core():
    """The overrun model must cover every length core will actually allow.

    Compared as SETS, because the order is not stable and is not meant to be.
    core.py declares (150, 240), and blockplan_adapter.py:35 then overwrites the
    global from rules.yaml's block_envelope.single_line.options_min, which lists
    the same two values as (240, 150). So the tuple this sees depends on whether
    anything has loaded config yet -- and in a full suite run something always
    has.

    An earlier version of this test compared tuples. It passed alone and failed
    in the suite, which is the worst way for a test to be wrong: it looks like a
    real regression in whichever change happens to be in flight. The requirement
    was never about order. It is that both allowed lengths are covered, so
    OverrunRisk fits a classifier for each and cannot be asked at inference for
    a length it never saw.
    """
    from blockplan_service import paths

    paths.ensure_import_paths()
    import core

    assert set(dm.BLOCK_LENGTHS) == set(core.ALLOWED_BLOCK_LENGTHS)
    assert len(set(dm.BLOCK_LENGTHS)) == len(dm.BLOCK_LENGTHS), "duplicate length"


# -- splits -----------------------------------------------------------------

def test_job_holdout_never_shares_a_job_between_train_and_test(table):
    """The property that makes it the honest split. If a job appeared on both
    sides, the model would be scored on work it had already done."""
    from sklearn.model_selection import GroupKFold

    groups = table.frame["job_id"].to_numpy()
    for train_index, test_index in GroupKFold(n_splits=5).split(
            table.frame, groups=groups):
        assert not set(groups[train_index]) & set(groups[test_index])


def test_realisation_holdout_shares_jobs_but_not_realisations(table):
    """The complement: same jobs, later executions. A different question, and
    the reason its numbers look better."""
    realisation = table.frame["realisation"].to_numpy()
    train, test = realisation < 20, realisation >= 20
    assert train.sum() and test.sum()
    assert not set(realisation[train]) & set(realisation[test])
    jobs = table.frame["job_id"].to_numpy()
    assert set(jobs[train]) == set(jobs[test])
