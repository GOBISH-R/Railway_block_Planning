"""Explanation service: blocks, refusals, theta propagation, determinism.

These tests are written to fail if the feature regresses, not merely to
exercise it. Where a test could pass vacuously (no data of the required kind in
the instance), it asserts the precondition first.
"""
from __future__ import annotations

import copy
import json

import pytest

from blockplan_service import (
    ExplanationService,
    PlanRequest,
    UnknownBlockError,
    UnknownJobError,
    departmental_chains,
)
from blockplan_service.explain import (
    REASON_OUTBID,
    REASON_RELIABILITY_BELOW_THETA,
    REASON_SCHEDULED,
)
from blockplan_service.planner import UnknownPlanError

BENCHMARK = PlanRequest(scenario="NORMAL_TRAFFIC", horizon_days=14, theta=0.90,
                        max_bundle_size=5, mc_samples=1500)
# URGENT_MAINTENANCE is the scenario that actually contains OUTBID refusals:
# capacity genuinely binds, so some deferred jobs still have admissible columns.
CONTENDED = PlanRequest(scenario="URGENT_MAINTENANCE", horizon_days=14, theta=0.90,
                        max_bundle_size=5, mc_samples=1500)


@pytest.fixture(scope="module")
def explainer(service) -> ExplanationService:
    return ExplanationService(service)


@pytest.fixture(scope="module")
def plan(service):
    return service.plan(BENCHMARK)


@pytest.fixture(scope="module")
def cross_department_block(service, plan):
    """A block with all three departments — the project's central claim."""
    blocks = [b for b in plan["blocks"] if len(b["dept_mix"]) >= 3]
    assert blocks, "no three-department block in the plan; test would be vacuous"
    return blocks[0]


# -- 1-5. block explanation ------------------------------------------------

def test_block_explanation_identifies_the_block(explainer, plan, cross_department_block):
    exp = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    assert exp["block_id"] == cross_department_block["block_id"]
    assert exp["decision_status"] == "SCHEDULED"
    assert exp["reason_code"] == REASON_SCHEDULED
    assert exp["section_id"] == cross_department_block["section_id"]
    assert exp["day"] == cross_department_block["day"]
    assert exp["length"] == cross_department_block["length"]
    assert exp["end_min"] == exp["start_min"] + exp["length"]


def test_block_explanation_carries_corridor_geography(explainer, plan,
                                                      cross_department_block, service):
    """A controller needs to know WHERE, not just which section id."""
    exp = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    section = exp["section"]
    assert section["from_station_code"] and section["to_station_code"]
    assert section["section_id"].startswith(section["from_station_code"])
    assert section["length_km"] > 0
    # Must agree with the frozen sections.csv, not be reconstructed.
    frozen = service.context.section_meta[cross_department_block["section_id"]]
    assert section["from_station_code"] == frozen["from_station_code"]
    assert section["to_station_code"] == frozen["to_station_code"]


def test_block_explanation_lists_exactly_the_included_jobs(explainer, plan,
                                                           cross_department_block):
    exp = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    assert [j["job_id"] for j in exp["jobs"]] == list(cross_department_block["job_ids"])
    for job in exp["jobs"]:
        assert job["dept"] in {"ENGG", "SNT", "TRD"}
        assert job["duration_mean_min"] > 0
        assert job["provenance"] == "D_SYNTHETIC", "maintenance demand is synthetic"


def test_block_explanation_reports_departments(explainer, plan, cross_department_block):
    exp = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    depts = [d["dept"] for d in exp["departments"]]
    assert depts == sorted(cross_department_block["dept_mix"])
    assert len(depts) == 3
    for entry in exp["departments"]:
        assert entry["job_count"] >= 1
        # Closing-chain constants must be the frozen ones, per department.
        assert entry["closing_chain_mean_min"] > 0


def test_block_explanation_cites_the_mandatory_pairing_rule(explainer, plan,
                                                            cross_department_block):
    """The cross-department claim rests on a manual, not on our preference."""
    exp = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    pairings = exp["constraints"]["mandatory_pairings"]
    assert pairings, "a three-department block should carry rule-mandated companions"
    for rule in pairings:
        assert rule["source"], "a pairing rule without a citation is not usable"
        assert any(manual in rule["source"] for manual in ("ACTM", "IRTMM"))
        assert rule["provenance"] == "C_RULE"
        assert rule["compelled_dept"] in {"ENGG", "SNT", "TRD"}


def test_block_explanation_reports_pairwise_compatibility(explainer, plan,
                                                          cross_department_block):
    exp = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    pairs = exp["constraints"]["pairwise"]
    n = len(cross_department_block["job_ids"])
    assert len(pairs) == n * (n - 1) // 2
    for pair in pairs:
        assert pair["compatible"], (
            "a selected bundle must be pairwise compatible; "
            f"{pair['job_a']}/{pair['job_b']} says {pair['incompatibility_reason']}"
        )
        assert pair["same_section_line"]
        assert not pair["shared_exclusive_resource"]


def test_block_explanation_reports_the_envelope(explainer, plan, cross_department_block):
    exp = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    env = exp["envelope"]
    # Compared as a set, not a sequence: config/rules.yaml declares
    # options_min: [240, 150] in the order the IRTMM norm is phrased ("one
    # 4-hour block, or two of 2.5 hours"), and that config value overwrites
    # core.py's own (150, 240) literal at load time. The order carries no
    # meaning; asserting it would pin a presentational detail of the YAML.
    assert set(env["allowed_block_lengths"]) == {150, 240}
    assert env["exceptional_length"] == 120
    assert env["selected_length"] == cross_department_block["length"]
    assert 0 < env["utilisation"] <= 1.5
    assert set(env["protection_regimes"]) <= {"T", "P", "D"}


def test_departmental_chains_match_the_frozen_reliability_formula(explainer, plan,
                                                                  service,
                                                                  cross_department_block,
                                                                  core_module):
    """The decomposition must equal core's own closed form.

    The Why panel draws these three chains. If this decomposition drifted from
    core.reliability_closed_form, the drawing would be a plausible-looking
    fiction. Asserting the product of the factors reproduces core's value is
    what keeps it honest.
    """
    plan_id = plan["plan_id"]
    internals = service.internals(plan_id)
    column = internals.blocks_by_id[cross_department_block["block_id"]]
    by_id = {j.id: j for j in internals.jobs}
    bundle = [by_id[jid] for jid in column.job_ids]

    terms = departmental_chains(bundle, column.window.length)
    product = 1.0
    for term in terms:
        product *= term.phi
    expected = core_module.reliability_closed_form(bundle, column.window.length)
    assert product == pytest.approx(expected, abs=1e-9)

    exp = explainer.explain_block(plan_id, cross_department_block["block_id"])
    assert len(exp["departmental_chains"]) == 3
    assert [c["dept"] for c in exp["departmental_chains"]] == sorted(
        cross_department_block["dept_mix"]
    )


def test_block_explanation_runs_no_solver_and_no_rng(explainer, plan,
                                                     cross_department_block,
                                                     core_module):
    """Explaining a block must not disturb planning state or cost a re-solve."""
    before = copy.deepcopy(core_module.RNG.bit_generator.state)
    exp = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    assert core_module.RNG.bit_generator.state == before, (
        "block explanation consumed RNG draws"
    )
    assert exp["computation"]["solver_calls"] == 0
    assert exp["computation"]["rng_consumed"] is False


def test_block_explanation_is_deterministic(explainer, plan, cross_department_block):
    a = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    b = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    a["computation"].pop("seconds", None)
    b["computation"].pop("seconds", None)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# -- 6-7. deferred jobs ----------------------------------------------------

def test_scheduled_job_explanation(explainer, plan, cross_department_block):
    job_id = cross_department_block["job_ids"][0]
    exp = explainer.explain_job(plan["plan_id"], job_id)
    assert exp["decision_status"] == "SCHEDULED"
    assert exp["scheduled_in"]["block_id"] == cross_department_block["block_id"]
    assert job_id not in exp["scheduled_in"]["shares_block_with"]
    assert exp["objective"]["deferral_penalty_avoided"] >= 0
    # Honesty about degeneracy, rather than claiming this placement was forced.
    assert exp["alternative_optima_exist"] is True
    assert exp["computation"]["solver_calls"] == 0


def test_deferred_job_is_explained_as_infeasible(explainer, plan):
    assert plan["deferred"], "no deferred job in the plan; test would be vacuous"
    job_id = plan["deferred"][0]["job_id"]
    exp = explainer.explain_job(plan["plan_id"], job_id)

    assert exp["decision_status"] == "DEFERRED"
    assert exp["verdict"] in ("INFEASIBLE", "OUTBID", "INFEASIBLE_WHEN_FORCED")
    assert exp["detail"]
    assert exp["evidence"]
    if exp["verdict"] == "INFEASIBLE":
        assert exp["candidate_columns"] == 0
        assert exp["levers"], "an INFEASIBLE verdict must say what was tried"
        for lever in exp["levers"]:
            assert "lever" in lever and "admissible" in lever


def test_infeasible_levers_cover_every_permitted_block_length(explainer, plan):
    """"No admissible column" must be backed by having tried each length."""
    job_id = plan["deferred"][0]["job_id"]
    exp = explainer.explain_job(plan["plan_id"], job_id)
    if exp["verdict"] != "INFEASIBLE":
        pytest.skip("deferred job is not INFEASIBLE in this instance")
    tested = {lever["lever"] for lever in exp["levers"] if lever["reliability"] is not None}
    assert any("240" in t for t in tested)
    assert any("150" in t for t in tested)
    assert any("120" in t for t in tested)
    if exp["reason_code"] == REASON_RELIABILITY_BELOW_THETA:
        assert not any(l["admissible"] for l in exp["levers"])


# -- 6. INFEASIBLE vs OUTBID -----------------------------------------------

def test_outbid_is_distinguished_from_infeasible(service, explainer):
    """The two verdicts are genuinely different answers, not one with a flag.

    OUTBID requires admissible columns to exist and the optimiser to have
    preferred deferral anyway. This test locates such a job by checking the
    retained columns directly, so it cannot pass by accident on an INFEASIBLE
    job.
    """
    contended = service.plan(CONTENDED)
    plan_id = contended["plan_id"]
    internals = service.internals(plan_id)

    outbid_candidates = [
        d["job_id"] for d in contended["deferred"]
        if any(d["job_id"] in c.job_ids for c in internals.columns)
    ]
    assert outbid_candidates, (
        "no deferred job has admissible columns in URGENT_MAINTENANCE; "
        "the OUTBID branch would be untested"
    )

    exp = explainer.explain_job(plan_id, outbid_candidates[0])
    assert exp["verdict"] == "OUTBID"
    assert exp["reason_code"] == REASON_OUTBID
    assert exp["candidate_columns"] > 0, "OUTBID means placements existed"
    assert exp["price_of_forcing"] is not None
    assert exp["would_go_in"] is not None
    assert exp["computation"]["resolve_required"] is True
    assert exp["computation"]["solver_calls"] == 1

    # An INFEASIBLE job in the same plan must look materially different.
    infeasible = [
        d["job_id"] for d in contended["deferred"]
        if not any(d["job_id"] in c.job_ids for c in internals.columns)
    ]
    assert infeasible
    other = explainer.explain_job(plan_id, infeasible[0])
    assert other["verdict"] == "INFEASIBLE"
    assert other["candidate_columns"] == 0
    assert other["computation"]["solver_calls"] == 0
    assert other.get("price_of_forcing") is None


def test_outbid_newly_displaced_excludes_already_deferred_jobs(service, explainer):
    """`displaced` overstates the consequence; `newly_displaced` must not.

    core returns the whole deferred set of the forced re-solve, most of which
    was already deferred in the baseline. Reporting that as "displaced by this
    job" would materially mislead a controller.
    """
    contended = service.plan(CONTENDED)
    plan_id = contended["plan_id"]
    internals = service.internals(plan_id)
    candidates = [
        d["job_id"] for d in contended["deferred"]
        if any(d["job_id"] in c.job_ids for c in internals.columns)
    ]
    assert candidates
    exp = explainer.explain_job(plan_id, candidates[0])

    baseline_deferred = set(internals.deferred_job_ids)
    assert set(exp["newly_displaced"]).isdisjoint(baseline_deferred), (
        "newly_displaced must exclude jobs that were already deferred"
    )
    assert set(exp["newly_displaced"]) <= set(exp["displaced"])
    assert len(exp["newly_displaced"]) <= len(exp["displaced"])


# -- 7. theta propagation --------------------------------------------------

def test_theta_is_passed_explicitly_to_explain_refusal(service, explainer, monkeypatch,
                                                       core_module):
    """The Phase 1 finding: core.explain_refusal's theta default binds at import.

    Relying on it would answer every request at 0.90 regardless of what was
    asked. This spy fails if the explicit keyword is ever dropped.
    """
    plan = service.plan(
        PlanRequest(scenario="NORMAL_TRAFFIC", horizon_days=14, theta=0.94,
                    max_bundle_size=5, mc_samples=1500)
    )
    assert plan["deferred"], "no deferred job at theta=0.94; test would be vacuous"

    seen: dict[str, object] = {}
    real = core_module.explain_refusal

    def spy(*args, **kwargs):
        seen.update(kwargs)
        seen["positional_count"] = len(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(core_module, "explain_refusal", spy)
    explainer.explain_job(plan["plan_id"], plan["deferred"][0]["job_id"])

    assert "theta" in seen, "theta was not passed as a keyword; the import-time default would apply"
    assert seen["theta"] == 0.94, f"theta not propagated from the request: {seen['theta']}"


def test_theta_from_the_request_reaches_the_lever_verdicts(service, explainer):
    """End-to-end evidence, independent of the spy.

    core writes the theta it used into its own lever verdict text. Planning at
    0.94 and finding "theta=0.9" there would mean the default had leaked
    through.
    """
    plan = service.plan(
        PlanRequest(scenario="NORMAL_TRAFFIC", horizon_days=14, theta=0.94,
                    max_bundle_size=5, mc_samples=1500)
    )
    job_id = plan["deferred"][0]["job_id"]
    exp = explainer.explain_job(plan["plan_id"], job_id)

    assert exp["applied_theta"] == 0.94
    verdicts = " ".join(l["verdict"] for l in (exp.get("levers") or []))
    if "theta=" in verdicts:
        assert "theta=0.94" in verdicts, f"stale theta in core's verdicts: {verdicts}"
        assert "theta=0.9 " not in verdicts

    # The admissibility flags this layer computes must use the request's theta.
    for lever in exp.get("levers") or []:
        if lever["reliability"] is not None:
            assert lever["admissible"] == (lever["reliability"] >= 0.94)


# -- 8. determinism --------------------------------------------------------

def test_deferred_explanation_is_deterministic(explainer, plan):
    """core.explain_refusal draws Monte Carlo samples on the INFEASIBLE branch.

    Without an RNG reset before the call, two identical explanation requests
    would return different lever reliabilities.
    """
    job_id = plan["deferred"][0]["job_id"]
    a = explainer.explain_job(plan["plan_id"], job_id)
    b = explainer.explain_job(plan["plan_id"], job_id)
    for payload in (a, b):
        payload["computation"].pop("seconds", None)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["computation"]["rng_reset_before_call"] is True


# -- error handling --------------------------------------------------------

def test_unknown_ids_raise_distinct_errors(explainer, plan):
    with pytest.raises(UnknownPlanError):
        explainer.explain_block("nosuchplan", "B0001")
    with pytest.raises(UnknownBlockError):
        explainer.explain_block(plan["plan_id"], "B9999")
    with pytest.raises(UnknownJobError):
        explainer.explain_job(plan["plan_id"], "J99999")


def test_provenance_is_never_misrepresented(explainer, plan, cross_department_block):
    """Synthetic demand must never be presented as real operational data."""
    exp = explainer.explain_block(plan["plan_id"], cross_department_block["block_id"])
    notice = exp["provenance"]["notice"].lower()
    assert "synthetic" in notice
    assert "not indian railways maintenance data" in notice
    assert exp["provenance"]["maintenance_demand"] == "D_SYNTHETIC"

    blob = json.dumps(exp).lower()
    for forbidden in ("ai decided", "the model predicted", "our ai",
                      "indian railways validated", "trained model"):
        assert forbidden not in blob, f"unsupported claim in explanation: {forbidden}"
