"""The asset-impact weighting: inert by default, declared when on.

Two things are under test, and the first matters more.

OFF MUST MEAN OFF. Not "changes little" -- the default must return the same job
objects untouched, leave plan 2db53586d84f alone, and add not one field to the
explanation response. Everything else here is optional; that is not.

WHEN ON, IT MUST DECLARE ITSELF. The weights are class E -- assumed, not
measured -- so a scaled criticality has to arrive labelled, with the factor and
the declared value beside it. A weighted number that reads as source data is
the failure mode this feature is most likely to produce.
"""
from __future__ import annotations

import pytest
import yaml

from blockplan_service import PlanRequest, PlanningService, asset_impact as ai
from blockplan_service.asset_impact import (
    AssetImpact,
    AssetImpactError,
    CriticalityWeighting,
    Disabled,
    Weights,
    resolve,
)

from test_reference_plan import REFERENCE_PLAN_ID, REFERENCE_REQUEST


@pytest.fixture(scope="module")
def enabled_config(tmp_path_factory) -> str:
    """The shipped weights with `enabled: true`, which is the sweep mechanism.

    The file in the repo stays disabled. Turning it on is done by pointing
    BLOCKPLAN_ASSET_IMPACT_CONFIG somewhere else, exactly as a sweep would.
    """
    raw = yaml.safe_load(open(ai.DEFAULT_CONFIG, encoding="utf-8"))
    raw["enabled"] = True
    path = tmp_path_factory.mktemp("weights") / "on.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return str(path)


@pytest.fixture(scope="module")
def weighting(enabled_config) -> AssetImpact:
    return AssetImpact(Weights.load(enabled_config))


# -- off is off --------------------------------------------------------------

def test_the_default_is_disabled():
    weighting = resolve({})
    assert isinstance(weighting, Disabled)
    assert weighting.enabled is False
    assert isinstance(weighting, CriticalityWeighting)


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_the_off_spellings_all_mean_off(value):
    assert resolve({"BLOCKPLAN_ASSET_IMPACT": value}).enabled is False


def test_the_shipped_weight_file_is_disabled():
    """The repo's own file must never ship enabled. Everything else here can be
    changed by a sweep; this cannot."""
    raw = yaml.safe_load(open(ai.DEFAULT_CONFIG, encoding="utf-8"))
    assert raw["enabled"] is False


def test_disabled_returns_the_same_objects_untouched(context):
    jobs = context.jobs_for("NORMAL_TRAFFIC")
    before = [(id(j), j.criticality) for j in jobs]

    returned = Disabled().apply(jobs)

    assert returned is jobs
    assert [(id(j), j.criticality) for j in returned] == before
    assert not any(hasattr(j, "asset_impact_factor") for j in returned)


def test_the_frozen_plan_id_is_unchanged_by_the_default(service):
    assert service.weighting.enabled is False
    assert service.plan_id_for(REFERENCE_REQUEST) == REFERENCE_PLAN_ID


@pytest.mark.slow
def test_the_default_path_still_produces_the_frozen_plan(context):
    planning = PlanningService(context=context)
    plan = planning.plan(REFERENCE_REQUEST, use_cache=False)
    assert plan["plan_id"] == REFERENCE_PLAN_ID
    assert plan["objective"] == 337.4
    assert plan["summary"]["blocks"] == 140


# -- turning it on takes two deliberate acts ---------------------------------

def test_the_flag_alone_is_not_enough():
    """The environment says this deployment wants it; the file says the weights
    are considered ready. Requiring both stops a half-edited weight file from
    moving a plan because somebody exported a variable."""
    with pytest.raises(AssetImpactError) as exc:
        resolve({"BLOCKPLAN_ASSET_IMPACT": "1"})
    assert "enabled: false" in str(exc.value)
    assert "class E" in str(exc.value) or "assumptions" in str(exc.value)


def test_both_switches_together_enable_it(enabled_config):
    weighting = resolve({"BLOCKPLAN_ASSET_IMPACT": "1",
                         "BLOCKPLAN_ASSET_IMPACT_CONFIG": enabled_config})
    assert weighting.enabled is True
    assert isinstance(weighting, CriticalityWeighting)


def test_a_nonsense_flag_value_is_refused():
    with pytest.raises(AssetImpactError):
        resolve({"BLOCKPLAN_ASSET_IMPACT": "maybe"})


def test_a_missing_weight_file_is_refused(tmp_path):
    with pytest.raises(AssetImpactError) as exc:
        Weights.load(str(tmp_path / "nope.yaml"))
    assert "nope.yaml" in str(exc.value)


def test_a_malformed_weight_file_is_refused(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("enabled: true\nasset: {TRACK_KM: 1.0}\n", encoding="utf-8")
    with pytest.raises(AssetImpactError) as exc:
        Weights.load(str(path))
    assert "malformed" in str(exc.value)


# -- the factor --------------------------------------------------------------

def test_the_asset_term_orders_the_classes_as_declared(weighting):
    section = "JTJ-TPT-UP"
    track = weighting.factor("THROUGH_TAMPING", section)         # TRACK_KM
    ohe = weighting.factor("OHE_INSPECTION", section)            # OHE_KM
    signal = weighting.factor("TRACK_CIRCUIT_MAINTENANCE", section)   # SIGNAL_POINT
    turnout = weighting.factor("TURNOUT_TAMPING", section)       # TURNOUT

    assert track == pytest.approx(1.00)
    assert track < ohe < signal < turnout


def test_an_uncatalogued_activity_gets_the_declared_default(weighting):
    """Four companion activities exist only as pairing-rule targets and have no
    asset class. They must not silently pick up someone else's weight."""
    assert weighting.factor("SNT_ASSOCIATION", "JTJ-TPT-UP") == pytest.approx(
        weighting.weights.default_asset_weight)


def test_an_unknown_section_does_not_crash(weighting):
    assert weighting.factor("THROUGH_TAMPING", "NO-SUCH-SECTION") > 0


def test_the_exposure_terms_are_inert_until_swept(weighting):
    """Shipped at weight 0, so enabling the feature changes only the asset term
    until someone deliberately raises them."""
    assert weighting.weights.support_weight == 0.0
    assert weighting.weights.headway_weight == 0.0


def test_the_exposure_terms_discriminate_once_swept(enabled_config, tmp_path):
    """A busy section with tight headway must outweigh a quiet one with loose
    headway, for the same work."""
    raw = yaml.safe_load(open(enabled_config, encoding="utf-8"))
    raw["support_trains"]["weight"] = 0.30
    raw["headway_min"]["weight"] = 0.25
    path = tmp_path / "swept.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    swept = AssetImpact(Weights.load(str(path)))
    exposure = ai.section_exposure()
    busy = next(s for s, v in exposure.items()
                if v["support_trains"] == 108 and v["headway_min"] == 4)
    quiet = next(s for s, v in exposure.items()
                 if v["support_trains"] == 18 and v["headway_min"] == 8)

    assert swept.factor("THROUGH_TAMPING", busy) > 1.0
    assert swept.factor("THROUGH_TAMPING", quiet) < 1.0


def test_the_factor_is_clamped(enabled_config, tmp_path):
    """An assumed weighting that can multiply urgency several-fold is not
    modulating the criticality, it is replacing it."""
    raw = yaml.safe_load(open(enabled_config, encoding="utf-8"))
    raw["asset"]["TURNOUT"] = 99.0
    raw["asset"]["TRACK_KM"] = 0.001
    path = tmp_path / "extreme.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    extreme = AssetImpact(Weights.load(str(path)))
    assert extreme.factor("TURNOUT_TAMPING", "JTJ-TPT-UP") == pytest.approx(
        extreme.weights.clamp_max)
    assert extreme.factor("THROUGH_TAMPING", "JTJ-TPT-UP") == pytest.approx(
        extreme.weights.clamp_min)


def test_the_single_line_term_cannot_fire_on_this_corridor():
    """Recorded as a fact about the data, not left to be discovered.

    is_single is 0 for all 52 sections of the Jolarpettai-Erode double line, so
    the multiplier is declared but inert here. If this ever fails, the corridor
    gained a single-line section and the weight becomes live.
    """
    exposure = ai.section_exposure()
    assert len(exposure) == 52
    assert all(v["is_single"] == 0.0 for v in exposure.values())


# -- application -------------------------------------------------------------

def test_applying_records_what_it_did(context, weighting):
    jobs = context.jobs_for("NORMAL_TRAFFIC")
    declared = {j.id: j.criticality for j in jobs}

    weighting.apply(jobs)

    changed = 0
    for job in jobs:
        assert job.declared_criticality == declared[job.id]
        expected = declared[job.id] * job.asset_impact_factor
        assert job.criticality == pytest.approx(expected)
        if job.asset_impact_factor != 1.0:
            changed += 1
    assert changed > 0, "the weighting changed nothing at all"


@pytest.mark.slow
def test_companions_are_unaffected_because_their_criticality_is_zero(
        context, weighting):
    """core.py:249 gives every companion criticality 0.0, so any factor
    multiplies to zero. 63 of the 238 jobs. Stated rather than assumed, because
    a reader could reasonably expect the weighting to reach them."""
    from blockplan_service import paths

    paths.ensure_import_paths()
    import core

    jobs = core.expand_mandatory_pairings(context.jobs_for("NORMAL_TRAFFIC"))
    companions = [j for j in jobs if j.parent_id is not None]
    assert len(companions) == 63

    weighting.apply(jobs)
    assert all(j.criticality == 0.0 for j in companions)


# -- disclosure --------------------------------------------------------------

def test_a_default_plan_discloses_nothing_extra(context):
    """The response must be byte-identical to what it was before this feature
    existed, or the default path is not really untouched."""
    from blockplan_service.explain import _criticality_provenance

    job = context.jobs_for("NORMAL_TRAFFIC")[0]
    assert _criticality_provenance(job) == {}


def test_a_weighted_job_arrives_labelled(context, weighting):
    """The scaled figure travels with its declared value, its factor, and the
    provenance grade of the weights that produced it."""
    from blockplan_service.explain import _criticality_provenance

    jobs = context.jobs_for("NORMAL_TRAFFIC")
    weighting.apply(jobs)
    disclosed = _criticality_provenance(jobs[0])

    assert set(disclosed) == {"declared_criticality", "asset_impact_factor",
                              "criticality_provenance"}
    assert disclosed["criticality_provenance"] == ai.PROVENANCE
    assert disclosed["criticality_provenance"].startswith("E:")


def test_the_weighting_names_itself_and_its_source(weighting):
    described = weighting.describe()
    assert "assumed" in described
    assert described.endswith(".yaml")


# -- plan identity -----------------------------------------------------------

def test_a_weighted_plan_does_not_take_the_frozen_plans_id(context, enabled_config):
    """It changes what deferring a job costs, so it changes the plan, so it
    must change the id."""
    weighted = PlanningService(
        context=context, weighting=AssetImpact(Weights.load(enabled_config)))
    assert weighted.plan_id_for(REFERENCE_REQUEST) != REFERENCE_PLAN_ID


def test_the_variant_id_distinguishes_the_two_optional_tracks(context,
                                                              enabled_config):
    """Learned durations and asset weighting are different changes and must not
    collide on one id."""
    class FakeLearned:
        name = "learned"

        def apply(self, jobs):
            return jobs

        def describe(self):
            return "fake"

    weighted = PlanningService(
        context=context, weighting=AssetImpact(Weights.load(enabled_config)))
    learned = PlanningService(context=context, durations=FakeLearned())
    both = PlanningService(context=context, durations=FakeLearned(),
                           weighting=AssetImpact(Weights.load(enabled_config)))

    ids = {weighted.plan_id_for(REFERENCE_REQUEST),
           learned.plan_id_for(REFERENCE_REQUEST),
           both.plan_id_for(REFERENCE_REQUEST),
           REFERENCE_PLAN_ID}
    assert len(ids) == 4, "two different configurations share a plan id"
