"""ML Phase 4: the experiment is set up so its result means something.

Not a test of the outcome. The outcome is a measurement and belongs in the
report; asserting a particular calibration error here would turn a finding into
a tripwire.

What is tested is the experimental design, because that is what makes the
measurement worth anything:

  * the model never sees the realisations it is scored on
  * both plans are scored against identical work and identical closing draws
  * the two plans are genuinely different plans, with different ids
  * the scoring is the dataset's own, not a reimplementation
"""
from __future__ import annotations

import importlib.util

import pytest

from blockplan_ml import experiment as ex

requires_lightgbm = pytest.mark.skipif(
    importlib.util.find_spec("lightgbm") is None,
    reason="LightGBM is not installed; the ML track is optional",
)


# -- the split ---------------------------------------------------------------

def test_training_and_scoring_windows_do_not_overlap():
    """The single property the whole experiment rests on."""
    assert not set(ex.TRAIN_REALISATIONS) & set(ex.TEST_REALISATIONS)
    assert len(ex.TRAIN_REALISATIONS) == 20
    assert len(ex.TEST_REALISATIONS) == 10
    assert set(ex.TRAIN_REALISATIONS) | set(ex.TEST_REALISATIONS) == set(range(30))


def test_the_experiment_plans_the_benchmark_request():
    """The instance must be the one every published figure describes, or the
    comparison is against a different problem."""
    from test_reference_plan import REFERENCE_REQUEST

    assert ex.REQUEST == REFERENCE_REQUEST


def test_the_held_out_actuals_cover_every_job_and_only_the_test_window():
    work = ex.held_out_actuals()
    assert len(work) == len(ex.TEST_REALISATIONS)
    for realisation in work:
        assert len(realisation) == 238, "175 jobs + 63 companions"
        assert all(v > 0 for v in realisation.values())


def test_the_held_out_actuals_differ_from_the_training_ones():
    """A silent off-by-one in the realisation filter would score the model on
    what it trained on and look like a triumph."""
    test = ex.held_out_actuals(ex.TEST_REALISATIONS)
    train = ex.held_out_actuals(ex.TRAIN_REALISATIONS[:10])
    assert test[0] != train[0]


# -- fairness ----------------------------------------------------------------

def test_the_closing_draws_are_reproducible_and_shared():
    """Both plans must meet the same closing times. Different draws would make
    the comparison about the sampling."""
    from blockplan_service import paths

    paths.ensure_import_paths()
    import core

    first = ex.closing_draws(core, 10)
    second = ex.closing_draws(core, 10)
    assert first == second
    assert len(first) == 10
    assert set(first[0]) == set(core.CLOSING)


def test_the_scorer_is_the_datasets_own():
    """Imported from src/score_execution.py -- the code that produced the frozen
    execution_scoring_summary.csv -- so these rows can be read beside it."""
    module = ex._score_execution_module()
    for name in ("score_block", "score_plan", "summarise"):
        assert hasattr(module, name), name
    assert module.CLOSING_SEED == ex.CLOSING_SEED


# -- the two plans -----------------------------------------------------------

@requires_lightgbm
@pytest.mark.slow
def test_the_two_plans_are_different_plans_with_different_ids(context):
    """If they came back identical, the learned durations never reached the
    theta filter and the experiment measured nothing."""
    from test_reference_plan import REFERENCE_PLAN_ID

    assumed, learned = ex.build_plans(context)

    assert assumed.plan["plan_id"] == REFERENCE_PLAN_ID
    assert learned.plan["plan_id"] != assumed.plan["plan_id"]

    assumed_blocks = {b["block_id"]: tuple(b["job_ids"])
                      for b in assumed.plan["blocks"]}
    learned_blocks = {b["block_id"]: tuple(b["job_ids"])
                      for b in learned.plan["blocks"]}
    assert assumed_blocks != learned_blocks, "the plan did not change"


@requires_lightgbm
@pytest.mark.slow
def test_the_assumed_plan_is_still_the_frozen_plan(context):
    """Phase 4 must not disturb the thing it is comparing against."""
    assumed, _ = ex.build_plans(context)
    assert assumed.plan["objective"] == 337.4
    assert assumed.plan["summary"]["blocks"] == 140
    assert assumed.plan["summary"]["jobs_deferred"] == 1
    assert assumed.plan["summary"]["traffic_cost"] == 299.2


@requires_lightgbm
@pytest.mark.slow
def test_both_plans_are_scored_and_produce_every_reported_metric(context):
    from blockplan_service import paths

    paths.ensure_import_paths()
    import core

    scorer = ex._score_execution_module()
    work = ex.held_out_actuals()
    closing = ex.closing_draws(core, len(work))

    for candidate in ex.build_plans(context):
        rows, summary = ex.score(candidate, core, scorer, work, closing)
        assert len(rows) == candidate.plan["summary"]["blocks"]
        for key, _ in ex._SCORED:
            assert key in summary, key
        assert 0.0 <= summary["plan_observed_rate_with_penalty"] <= 1.0
