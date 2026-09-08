"""The duration plug-in, and the gate the whole ML track sits behind.

The gate is one sentence: with the flag unset, nothing changes. Not "changes
very little" -- the default path must return plan 2db53586d84f with the same
140 blocks and the same objective, because every benchmark number in this
project came from it.

Everything else here is about keeping that true by construction rather than by
luck: the catalogue source is a genuine no-op, the ML libraries are not
imported unless asked for, an unknown flag value is refused rather than
silently ignored, and a learned plan is not handed out under the frozen plan's
id.

The tests that fit a model are marked slow and skipped when LightGBM is absent,
so a checkout that never installed it still runs the suite.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from blockplan_service import PlanRequest, PlanningService
from blockplan_service.durations import (
    CATALOGUE,
    LEARNED,
    CatalogueDurations,
    DurationSource,
)
from blockplan_service.planner import resolve_durations

from test_reference_plan import REFERENCE_PLAN_ID, REFERENCE_REQUEST

import importlib.util

requires_lightgbm = pytest.mark.skipif(
    importlib.util.find_spec("lightgbm") is None,
    reason="LightGBM is not installed; the ML track is optional",
)


# -- the default -------------------------------------------------------------

def test_the_default_is_the_catalogue():
    source = resolve_durations()
    assert isinstance(source, CatalogueDurations)
    assert source.name == CATALOGUE


def test_the_catalogue_source_is_a_genuine_no_op(context):
    """Not "returns equal jobs" -- returns THE SAME OBJECTS, untouched.

    A copy, or a round trip through float(), would be a way for the default
    path to drift away from the frozen plan without anyone editing anything.
    """
    jobs = context.jobs_for("NORMAL_TRAFFIC")
    before = [(id(j), j.dur_mean, j.dur_sd) for j in jobs]

    returned = CatalogueDurations().apply(jobs)

    assert returned is jobs
    assert [(id(j), j.dur_mean, j.dur_sd) for j in returned] == before


def test_a_service_with_no_flag_uses_the_catalogue(service):
    assert service.durations.name == CATALOGUE


def test_the_frozen_plan_id_is_unchanged_by_the_plug_in(service):
    """The plug-in added a branch to plan id derivation. On the default it must
    take the untouched path."""
    assert service.plan_id_for(REFERENCE_REQUEST) == REFERENCE_PLAN_ID
    assert service.plan_id_for(REFERENCE_REQUEST) == REFERENCE_REQUEST.cache_key()


@pytest.mark.slow
def test_the_default_path_still_produces_the_frozen_plan(context):
    """The gate, run through the service rather than trusted.

    test_reference_plan.py asserts this too. It is repeated here because THIS
    file is where a change to the duration path would land, and a gate in
    another file is easy to forget.
    """
    planning = PlanningService(context=context)
    plan = planning.plan(REFERENCE_REQUEST, use_cache=False)

    assert plan["plan_id"] == REFERENCE_PLAN_ID
    assert plan["objective"] == 337.4
    assert plan["summary"]["blocks"] == 140
    assert plan["summary"]["jobs_deferred"] == 1
    assert plan["summary"]["traffic_cost"] == 299.2


def test_the_ml_libraries_are_not_imported_on_the_default_path():
    """A fresh interpreter, because sys.modules in this one is already full of
    whatever the rest of the suite imported.

    pandas is deliberately NOT checked: OR-Tools imports it, so it has been on
    the default path since long before the ML track existed. The promise is
    about LightGBM, scikit-learn and blockplan_ml.
    """
    script = (
        "import sys;"
        "sys.path.insert(0, '.');"
        "from blockplan_service import PlanningService;"
        "PlanningService();"
        "print(sorted(m for m in sys.modules "
        "if m.split('.')[0] in {'lightgbm', 'sklearn', 'blockplan_ml'}))"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, cwd=_backend_dir())
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip().splitlines()[-1] == "[]"


def _backend_dir() -> str:
    import os

    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# -- resolution --------------------------------------------------------------

@pytest.mark.parametrize("value", ["", "catalogue", "CATALOGUE", " Catalogue "])
def test_catalogue_is_accepted_in_any_reasonable_spelling(value, monkeypatch):
    monkeypatch.setenv("BLOCKPLAN_DURATION_SOURCE", value)
    assert resolve_durations().name == CATALOGUE


@requires_lightgbm
def test_an_unknown_source_is_refused_rather_than_falling_back(monkeypatch):
    """Falling back to the catalogue would look like it worked, and the
    resulting plan would be presented as a learned one."""
    from blockplan_ml.duration_source import DurationSourceError, resolve

    with pytest.raises(DurationSourceError) as exc:
        resolve({"BLOCKPLAN_DURATION_SOURCE": "lightgbm"})
    assert "lightgbm" in str(exc.value)
    assert CATALOGUE in str(exc.value) and LEARNED in str(exc.value)


@requires_lightgbm
@pytest.mark.parametrize("text,expected", [
    ("0-3", (0, 1, 2, 3)),
    ("0,2,4", (0, 2, 4)),
])
def test_the_training_window_can_be_named(text, expected):
    from blockplan_ml.duration_source import _parse_window

    assert _parse_window(text) == expected


@requires_lightgbm
def test_a_malformed_training_window_is_refused():
    from blockplan_ml.duration_source import DurationSourceError, _parse_window

    with pytest.raises(DurationSourceError):
        _parse_window("first twenty")


# -- moment matching ---------------------------------------------------------

@requires_lightgbm
def test_the_quantile_ladder_becomes_a_mean_and_an_sd():
    """core.py reads dur_mean and dur_sd as the arithmetic moments of the
    duration distribution and fits its own lognormal, so that is what has to
    come out -- recovered here from a ladder generated by a KNOWN lognormal.
    """
    import numpy as np

    from blockplan_ml.duration_source import lognormal_moments

    mu, sigma = np.log(60.0), 0.3
    ladder = {t: np.array([float(np.exp(mu + sigma * z))])
              for t, z in ((0.1, -1.2815515655446004), (0.5, 0.0),
                           (0.9, 1.2815515655446004))}
    mean, sd = lognormal_moments(ladder)

    assert mean[0] == pytest.approx(np.exp(mu + sigma ** 2 / 2), rel=1e-6)
    assert sd[0] == pytest.approx(
        mean[0] * np.sqrt(np.exp(sigma ** 2) - 1), rel=1e-6)


@requires_lightgbm
def test_a_collapsed_ladder_cannot_produce_a_deterministic_job():
    """A degenerate prediction would give sd 0, core.py would treat the job as
    certain, and every bundle containing it would clear theta. Floored instead.
    """
    import numpy as np

    from blockplan_ml.duration_source import MIN_SD_MIN, lognormal_moments

    ladder = {t: np.array([50.0]) for t in (0.1, 0.5, 0.9)}
    _, sd = lognormal_moments(ladder)
    assert sd[0] >= MIN_SD_MIN


# -- the learned source ------------------------------------------------------

@requires_lightgbm
def test_the_serving_frame_is_built_only_from_core_job_attributes(context):
    """If this reached for a jobs.csv column, it would work in tests and fail
    on the seven scenarios that have no such row."""
    from blockplan_ml import training_table as tt
    from blockplan_ml.duration_source import job_frame, join_reference

    jobs = context.jobs_for("HEAVY_FREIGHT")
    features = join_reference(job_frame(jobs))
    for column in tt.build(tt.SERVING).feature_columns:
        assert column in features.columns, column


@requires_lightgbm
@pytest.mark.slow
def test_learned_durations_replace_both_parameters(context):
    from blockplan_ml.duration_source import LearnedDurations

    jobs = context.jobs_for("NORMAL_TRAFFIC")
    before = [(j.dur_mean, j.dur_sd) for j in jobs]

    LearnedDurations(realisations=range(0, 20)).apply(jobs)
    after = [(j.dur_mean, j.dur_sd) for j in jobs]

    assert after != before, "the learned source changed nothing"
    assert all(m > 0 and s > 0 for m, s in after)


@requires_lightgbm
@pytest.mark.slow
def test_a_learned_plan_does_not_take_the_frozen_plans_id(context):
    """Two materially different plans must not share an id.

    Measured: the same request gives objective 337.4 / 140 blocks from the
    catalogue and 428.4 / 137 from the model. Before plan_id_for branched on
    the source, both were handed out as 2db53586d84f -- and would have
    collided in the plan cache and in the plans table.
    """
    from blockplan_ml.duration_source import LearnedDurations

    learned = PlanningService(context=context,
                              durations=LearnedDurations(realisations=range(0, 20)))
    assert learned.plan_id_for(REFERENCE_REQUEST) != REFERENCE_PLAN_ID


def test_the_protocol_is_satisfied_by_the_default():
    assert isinstance(CatalogueDurations(), DurationSource)
