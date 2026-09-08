"""Explanation service — why the plan looks like this.

This is a decision-support explanation layer for a constraint-optimisation and
stochastic-simulation system. It is not a natural-language layer and it does
not narrate. Every field it returns is either read directly from the planning
result, or computed by a frozen core function that the planner itself used.

Three rules govern this module:

1. **No invented reasons.** If the planner does not expose why something
   happened, this module says so rather than constructing a plausible story.
   The clearest example is block selection: because this instance is highly
   degenerate (many distinct plans share the identical optimal objective), no
   honest explanation can claim a particular block was chosen *over* some
   alternative. What can be said is that the plan as a whole is cost-optimal
   and that this block satisfies the stated constraints -- so that is what is
   said, and `alternative_optima_exist` flags the rest.

2. **No extra solver calls unless the core requires one.** Block explanation
   runs no solver and consumes no RNG: the reliability figure is the one the
   optimiser already computed, and the per-length figures use the closed-form
   approximation. Only the OUTBID branch of a refusal re-solves, because
   core.explain_refusal prices a forced insertion by re-solving -- that is the
   frozen design, and it is reported in the response rather than hidden.

3. **Theta is always passed explicitly.** core.explain_refusal declares
   `theta: float = THETA`, bound at import time, so the module default would
   silently answer at 0.90 whatever the request asked for.
"""
from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass
from typing import Any, Mapping

from . import paths
from .planner import PlanInternals, PlanningService, UnknownPlanError, planning_lock

paths.ensure_import_paths()

import core  # noqa: E402

# Reason codes. Each maps to something the planner or the frozen core actually
# reports -- none is inferred from vibes.
REASON_SCHEDULED = "SCHEDULED_IN_COST_OPTIMAL_PLAN"
REASON_CLASS_D_TRAIN_MOVEMENTS = "INFEASIBLE_REQUIRES_TRAIN_MOVEMENTS"
REASON_CLASS_D_LIVE_OHE = "INFEASIBLE_REQUIRES_LIVE_OHE"
REASON_RELIABILITY_BELOW_THETA = "INFEASIBLE_RELIABILITY_BELOW_THETA"
REASON_NO_ADMISSIBLE_COLUMN = "INFEASIBLE_NO_ADMISSIBLE_COLUMN"
REASON_OUTBID = "OUTBID_DEFERRAL_CHEAPER_THAN_INSERTION"
REASON_INFEASIBLE_WHEN_FORCED = "INFEASIBLE_WHEN_FORCED"

# Provenance classes, per the dataset's own five-class system.
PROV_RULE = "C_RULE"
PROV_SYNTHETIC = "D_SYNTHETIC"
PROV_ASSUMPTION = "E_ASSUMPTION"


def _criticality_provenance(job) -> dict:
    """Disclose an adjusted criticality AS adjusted, or say nothing at all.

    asset_impact.apply() records the declared value and the factor on the job
    when it scales one. If it never ran, these attributes do not exist and this
    returns {} -- so a default plan's response is byte-identical to what it was
    before the weighting existed.
    """
    factor = getattr(job, "asset_impact_factor", None)
    if factor is None:
        return {}
    from .asset_impact import PROVENANCE

    return {
        "declared_criticality": getattr(job, "declared_criticality", None),
        "asset_impact_factor": round(float(factor), 4),
        "criticality_provenance": PROVENANCE,
    }


class ExplanationUnavailableError(RuntimeError):
    """The plan exists but its pipeline artefacts have been evicted (-> 409).

    Plan responses are kept indefinitely (the UI holds two side by side to show
    "before and after the disruption"), but the artefacts needed to explain them
    are far larger and are bounded. When the two disagree, say so precisely
    instead of claiming the plan does not exist -- a bare 404 for a plan the
    client is currently displaying would be actively confusing.
    """


class UnknownBlockError(KeyError):
    """Block id not present in this plan (-> 404)."""


class UnknownJobError(KeyError):
    """Job id not present in this plan's demand (-> 404)."""


@dataclass(frozen=True)
class _ChainTerm:
    dept: str
    mean_min: float
    sd_min: float
    z: float
    phi: float


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def departmental_chains(bundle: list[Any], block_len: int) -> list[_ChainTerm]:
    """Decompose core.reliability_closed_form into its per-department factors.

    This is not a reimplementation of the reliability model. It is the same
    algebra core.reliability_closed_form() evaluates, kept term-by-term instead
    of collapsed into a product, because the per-department (mean, sd) pairs are
    exactly what the Why panel draws as three bars against the block envelope.

    A test asserts that the product of the phi factors returned here equals
    core.reliability_closed_form() for the same bundle, so any drift from the
    frozen formula fails the suite rather than silently misleading a controller.
    """
    depts = sorted({j.dept for j in bundle})
    n_dep = len(depts)
    infl = 1.0 + core.KAPPA * (n_dep - 1)
    extra_close = core.LAMBDA_CLOSE * (n_dep - 1)

    terms: list[_ChainTerm] = []
    for d in depts:
        mean = (sum(j.dur_mean for j in bundle if j.dept == d)
                + core.CLOSING[d][0] + extra_close)
        var = (sum((j.dur_sd * infl) ** 2 for j in bundle if j.dept == d)
               + (core.CLOSING[d][1] * infl) ** 2)
        # Cross-department precedence: a predecessor in another department
        # pushes this department's chain out by its whole duration.
        for j in bundle:
            if j.dept != d:
                continue
            for pid in j.after:
                pred = next((p for p in bundle if p.id == pid), None)
                if pred is not None and pred.dept != d:
                    mean += pred.dur_mean
                    var += (pred.dur_sd * infl) ** 2
        sd = math.sqrt(var)
        z = (block_len - mean) / sd
        terms.append(_ChainTerm(dept=d, mean_min=mean, sd_min=sd, z=z, phi=_phi(z)))
    return terms


class ExplanationService:
    """Builds structured explanations from a retained planning result."""

    def __init__(self, service: PlanningService) -> None:
        self.service = service

    # -- helpers -----------------------------------------------------------

    def _internals(self, plan_id: str) -> PlanInternals:
        plan_known = self.service.cached_plan(plan_id) is not None
        if not plan_known:
            raise UnknownPlanError(plan_id)
        try:
            return self.service.internals(plan_id)
        except UnknownPlanError as exc:
            raise ExplanationUnavailableError(
                f"plan {plan_id} is still cached but its planning artefacts have "
                f"been evicted; re-run the plan to explain it"
            ) from exc

    def _section_meta(self, section_id: str) -> dict[str, Any]:
        meta = self.service.context.section_meta.get(section_id)
        return dict(meta) if meta else {"section_id": section_id}

    def _job_view(self, job: Any) -> dict[str, Any]:
        """One job, as the explanation surfaces it."""
        protections = [name for name, needed in
                       (("T", job.needs_T), ("P", job.needs_P), ("D", job.needs_D))
                       if needed]
        return {
            "job_id": job.id,
            "dept": job.dept,
            "activity": job.activity,
            "section_id": job.section_id,
            "km_from": round(job.km_from, 3),
            "km_to": round(job.km_to, 3),
            "duration_mean_min": job.dur_mean,
            "duration_sd_min": job.dur_sd,
            "due_day": job.due_day,
            # The value the optimiser actually used. When the asset-impact
            # weighting is on this is a SCALED figure, so the two fields below
            # appear alongside it and say so -- a weighted number must not be
            # readable as source data. Absent entirely when nothing was
            # applied, so the default response is unchanged.
            "criticality": job.criticality,
            **_criticality_provenance(job),
            "protection_required": protections,
            "resources": list(job.resources),
            "is_companion": job.is_companion,
            "parent_id": job.parent_id,
            "needs_train_movements": job.needs_train_movements,
            "needs_live_ohe": job.needs_live_ohe,
            "provenance": PROV_SYNTHETIC,
        }

    def _companion_rules(self, bundle: list[Any]) -> list[dict[str, Any]]:
        """Rule-mandated companions in this bundle, with their manual citation.

        This is the cross-department claim the project rests on: the pairing is
        compelled by an Indian Railways manual, not proposed by this system.
        """
        rules_by_activity = self.service.context.pairing_rules
        out: list[dict[str, Any]] = []
        by_id = {j.id: j for j in bundle}
        for job in bundle:
            if job.parent_id is None:
                continue
            parent = by_id.get(job.parent_id)
            if parent is None:
                continue
            for rule in rules_by_activity.get(parent.activity, ()):  # type: ignore[arg-type]
                if (rule["compelled_dept"] == job.dept
                        and rule["companion_activity"] == job.activity):
                    out.append({
                        "parent_job_id": parent.id,
                        "parent_activity": parent.activity,
                        "companion_job_id": job.id,
                        "compelled_dept": job.dept,
                        "companion_activity": job.activity,
                        "must_follow_parent": rule["must_follow_parent"],
                        "source": rule["source"],
                        "confidence": rule["confidence"],
                        "provenance": PROV_RULE,
                    })
                    break
        return out

    def _pair_constraints(self, bundle: list[Any]) -> list[dict[str, Any]]:
        """Why each pair of jobs may legally share one block.

        Uses core.pairwise_compatible, the same function the bundle enumerator
        used. Every pair in a selected bundle must return compatible; if one did
        not, that is a genuine inconsistency and it is surfaced rather than
        hidden.
        """
        out: list[dict[str, Any]] = []
        for i, a in enumerate(bundle):
            for b in bundle[i + 1:]:
                ok, reason = core.pairwise_compatible(a, b)
                out.append({
                    "job_a": a.id,
                    "job_b": b.id,
                    "compatible": bool(ok),
                    "same_section_line": a.section_id == b.section_id,
                    "footprints_overlap": core.footprints_overlap(a, b),
                    "rule_paired": core.related(a, b),
                    "shared_exclusive_resource": sorted(
                        set(a.resources) & set(b.resources)
                    ),
                    "incompatibility_reason": reason or None,
                })
        return out

    # -- block explanation -------------------------------------------------

    def explain_block(self, plan_id: str, block_id: str) -> dict[str, Any]:
        """Explain one scheduled block. No solver call, no RNG consumption.

        Deliberately does NOT take the planning lock, so the Why panel stays
        responsive while a re-plan is running. That is safe here because of
        exactly what this method reads from core: KAPPA, LAMBDA_CLOSE, CLOSING,
        MAX_SPAN_KM and the block-envelope constants, all of which come from the
        frozen YAML config and are reloaded to identical values on every
        request. The one global that genuinely varies per request is THETA, and
        this method never reads it -- it uses the theta recorded on the plan
        being explained.
        """
        started = time.perf_counter()
        internals = self._internals(plan_id)
        column = internals.blocks_by_id.get(block_id)
        if column is None:
            raise UnknownBlockError(block_id)

        by_id = {j.id: j for j in internals.jobs}
        bundle = [by_id[jid] for jid in column.job_ids]
        window = column.window
        theta = internals.request.theta

        depts = sorted({j.dept for j in bundle})
        chains = departmental_chains(bundle, window.length)

        # Envelope: which block lengths the corridor norms permit, and the
        # closed-form reliability at each. Closed form, not Monte Carlo, so this
        # view is deterministic and consumes no RNG.
        allowed = list(core.ALLOWED_BLOCK_LENGTHS)
        envelope_lengths = sorted({*allowed, core.EXCEPTIONAL_LENGTH})
        reliability_by_length = {
            str(length): round(core.reliability_closed_form(bundle, length), 4)
            for length in envelope_lengths
        }

        protections = sorted({p for j in bundle for p, needed in
                              (("T", j.needs_T), ("P", j.needs_P), ("D", j.needs_D))
                              if needed})
        work_minutes = sum(j.dur_mean for j in bundle)

        return {
            "plan_id": plan_id,
            "block_id": block_id,
            "scenario": internals.request.scenario,
            "decision_status": "SCHEDULED",
            "reason_code": REASON_SCHEDULED,
            "section_id": window.section_id,
            "section": self._section_meta(window.section_id),
            "day": window.day,
            "start_min": window.start_min,
            "end_min": window.end_min,
            "length": window.length,
            "reliability": round(column.reliability, 4),
            "jobs": [self._job_view(j) for j in bundle],
            "departments": [
                {
                    "dept": d,
                    "job_count": sum(1 for j in bundle if j.dept == d),
                    "work_minutes": round(
                        sum(j.dur_mean for j in bundle if j.dept == d), 1
                    ),
                    "closing_chain_mean_min": core.CLOSING[d][0],
                    "closing_chain_sd_min": core.CLOSING[d][1],
                }
                for d in depts
            ],
            "departmental_chains": [
                {
                    "dept": t.dept,
                    "mean_min": round(t.mean_min, 2),
                    "sd_min": round(t.sd_min, 2),
                    "z": round(t.z, 4),
                    "phi": round(t.phi, 4),
                }
                for t in chains
            ],
            "envelope": {
                "allowed_block_lengths": allowed,
                "exceptional_length": core.EXCEPTIONAL_LENGTH,
                "selected_length": window.length,
                "is_exceptional_length": window.length == core.EXCEPTIONAL_LENGTH,
                "work_minutes": round(work_minutes, 1),
                "utilisation": round(work_minutes / window.length, 3),
                "protection_regimes": protections,
            },
            "reliability_by_allowed_length": reliability_by_length,
            "constraints": {
                "applied_theta": theta,
                "meets_theta": column.reliability >= theta,
                "max_span_km": core.MAX_SPAN_KM,
                "bundle_span_km": round(
                    max(j.km_to for j in bundle) - min(j.km_from for j in bundle), 3
                ),
                "mandatory_pairings": self._companion_rules(bundle),
                "pairwise": self._pair_constraints(bundle),
            },
            "objective": {
                "traffic_cost": round(window.traffic_cost, 2),
                "expected_overrun_cost": round(column.exp_overrun_cost, 2),
                "column_total_cost": round(column.total_cost, 2),
                "plan_objective": round(internals.objective, 2),
                "units": "weighted train-minutes",
            },
            "evidence": self._block_evidence(column, bundle, chains, theta),
            "provenance": {
                "infrastructure_and_timetable": "A_REAL / B_DERIVED",
                "maintenance_demand": PROV_SYNTHETIC,
                "pairing_rules": PROV_RULE,
                "theta_kappa_lambda_closing": PROV_ASSUMPTION,
                "notice": (
                    "Maintenance jobs and block requests are synthetic, generated "
                    "from documented distributions. Infrastructure, stations and "
                    "train schedules are real public data. This is not Indian "
                    "Railways maintenance data."
                ),
            },
            "computation": {
                "solver_calls": 0,
                "rng_consumed": False,
                "reliability_source": "monte_carlo_from_planning_run",
                "reliability_by_length_source": "closed_form_normal_approximation",
                "seconds": round(time.perf_counter() - started, 4),
            },
        }

    def _block_evidence(self, column, bundle, chains, theta) -> list[dict[str, Any]]:
        """The specific facts supporting this block, each traceable to a source."""
        binding = max(chains, key=lambda t: t.mean_min)
        evidence = [
            {
                "code": "HANDBACK_IS_MAX_OF_CHAINS",
                "statement": (
                    f"The block ends when the last of {len(chains)} independent "
                    f"departmental chains finishes; {binding.dept} has the longest "
                    f"modelled chain at {binding.mean_min:.1f} min "
                    f"(sd {binding.sd_min:.1f})."
                ),
                "source": "core.reliability_closed_form structure",
                "provenance": PROV_ASSUMPTION,
            },
            {
                "code": "MEETS_RELIABILITY_FLOOR",
                "statement": (
                    f"Modelled P(hand back within {column.window.length} min) = "
                    f"{column.reliability:.3f}, against the policy floor "
                    f"theta = {theta}."
                ),
                "source": "core.reliability_mc, computed during the planning run",
                "provenance": PROV_ASSUMPTION,
            },
            {
                "code": "TRAFFIC_COST_PRICED",
                "statement": (
                    f"Taking this window costs {column.window.traffic_cost:.1f} "
                    f"weighted train-minutes of delay, priced by the queue model "
                    f"against the published timetable."
                ),
                "source": "core.traffic_cost via core.generate_windows",
                "provenance": "B_DERIVED",
            },
        ]
        rules = self._companion_rules(bundle)
        if rules:
            cited = rules[0]
            evidence.append({
                "code": "CROSS_DEPARTMENT_WORK_IS_RULE_MANDATED",
                "statement": (
                    f"{cited['parent_activity']} compels "
                    f"{cited['compelled_dept']} to perform "
                    f"{cited['companion_activity']} in the same block."
                ),
                "source": cited["source"],
                "provenance": PROV_RULE,
            })
        return evidence

    # -- job explanation ---------------------------------------------------

    def explain_job(self, plan_id: str, job_id: str) -> dict[str, Any]:
        """Explain why one job is scheduled or deferred."""
        internals = self._internals(plan_id)
        try:
            job = internals.job(job_id)
        except KeyError as exc:
            raise UnknownJobError(job_id) from exc

        for block_id, column in internals.blocks_by_id.items():
            if job_id in column.job_ids:
                return self._explain_scheduled_job(internals, plan_id, job, block_id, column)
        return self._explain_deferred_job(internals, plan_id, job)

    def _explain_scheduled_job(self, internals, plan_id, job, block_id, column):
        by_id = {j.id: j for j in internals.jobs}
        bundle = [by_id[jid] for jid in column.job_ids]
        penalty = core.deferral_penalty(job, internals.request.horizon_days)
        return {
            "plan_id": plan_id,
            "job_id": job.id,
            "scenario": internals.request.scenario,
            "decision_status": "SCHEDULED",
            "reason_code": REASON_SCHEDULED,
            "applied_theta": internals.request.theta,
            "job": self._job_view(job),
            "scheduled_in": {
                "block_id": block_id,
                "section_id": column.window.section_id,
                "day": column.window.day,
                "start_min": column.window.start_min,
                "length": column.window.length,
                "reliability": round(column.reliability, 4),
                "shares_block_with": [jid for jid in column.job_ids if jid != job.id],
                "departments_in_block": sorted({b.dept for b in bundle}),
            },
            "objective": {
                "deferral_penalty_avoided": round(penalty, 2),
                "block_traffic_cost": round(column.window.traffic_cost, 2),
                "block_expected_overrun_cost": round(column.exp_overrun_cost, 2),
                "units": "weighted train-minutes",
            },
            "evidence": [
                {
                    "code": "PLACED_IN_ADMISSIBLE_BLOCK",
                    "statement": (
                        f"This job sits in block {block_id}, whose modelled "
                        f"hand-back reliability {column.reliability:.3f} meets the "
                        f"policy floor theta = {internals.request.theta}."
                    ),
                    "source": "planning result",
                    "provenance": PROV_ASSUMPTION,
                },
                {
                    "code": "DEFERRAL_WOULD_HAVE_COST",
                    "statement": (
                        f"Leaving it undone across the horizon would have added a "
                        f"deferral penalty of {penalty:.1f} to the objective."
                    ),
                    "source": "core.deferral_penalty",
                    "provenance": PROV_ASSUMPTION,
                },
            ],
            "alternative_optima_exist": True,
            "caveat": (
                "The plan as a whole is cost-optimal. Because many distinct plans "
                "share the identical optimal objective on this instance, no claim "
                "is made that this job could not have been placed elsewhere at the "
                "same cost."
            ),
            "computation": {"solver_calls": 0, "rng_consumed": False},
        }

    def _explain_deferred_job(self, internals, plan_id, job):
        """Refusal explanation, via the frozen core.

        theta is passed EXPLICITLY. core.explain_refusal declares
        `theta: float = THETA` and that default binds at import time, so relying
        on it would answer every request at 0.90 regardless of what was asked.
        """
        theta = internals.request.theta
        started = time.perf_counter()

        # core.explain_refusal draws Monte Carlo samples on the INFEASIBLE
        # branch, so the RNG is reset to the plan's own starting state first --
        # otherwise two identical explanation requests would return different
        # lever reliabilities.
        with planning_lock():
            core.RNG.bit_generator.state = copy.deepcopy(dict(internals.rng_state))
            raw = core.explain_refusal(
                job,
                list(internals.jobs),
                list(internals.columns),
                list(internals.windows),
                list(self.service.context.sections),
                internals.request.horizon_days,
                internals.objective,
                theta=theta,          # explicit -- never the import-time default
            )
        seconds = time.perf_counter() - started

        verdict = raw["verdict"]
        if verdict == "OUTBID":
            body = self._shape_outbid(raw, internals)
            solver_calls = 1
        elif verdict == "INFEASIBLE_WHEN_FORCED":
            body = {
                "reason_code": REASON_INFEASIBLE_WHEN_FORCED,
                "candidate_columns": raw.get("candidate_columns", 0),
                "levers": [],
                "detail": (
                    "Admissible columns exist for this job, but no feasible plan "
                    "exists once it is forced in."
                ),
            }
            solver_calls = 1
        else:
            body = self._shape_infeasible(raw, job, theta)
            solver_calls = 0

        return {
            "plan_id": plan_id,
            "job_id": job.id,
            "scenario": internals.request.scenario,
            "decision_status": "DEFERRED",
            "verdict": verdict,
            "applied_theta": theta,
            "job": self._job_view(job),
            **body,
            "provenance": {
                "maintenance_demand": PROV_SYNTHETIC,
                "theta": PROV_ASSUMPTION,
                "notice": (
                    "Maintenance demand is synthetic. This is not Indian Railways "
                    "maintenance data."
                ),
            },
            "computation": {
                "solver_calls": solver_calls,
                "resolve_required": verdict in ("OUTBID", "INFEASIBLE_WHEN_FORCED"),
                "lever_mc_samples": core.reliability_mc.__defaults__[0],
                "rng_reset_before_call": True,
                "seconds": round(seconds, 3),
                "note": (
                    "The OUTBID branch re-solves the model with the job forced in, "
                    "to price the insertion. That re-solve is how the frozen core "
                    "produces the price; it is not an additional explanation step."
                ) if verdict == "OUTBID" else (
                    "No solver call. Lever reliabilities are Monte Carlo estimates "
                    "at the core's own default sample count, which may differ from "
                    "the mc_samples the plan itself used."
                ),
            },
        }

    def _shape_infeasible(self, raw, job, theta) -> dict[str, Any]:
        levers = [
            {
                "lever": lever["lever"],
                "reliability": lever["reliability"],
                "admissible": (lever["reliability"] is not None
                               and lever["reliability"] >= theta),
                "verdict": lever["verdict"],
            }
            for lever in raw.get("levers", [])
        ]

        # The Class D verdicts are taken from core's own lever text rather than
        # inferred from the job's flags. core.explain_refusal emits these as
        # levers with `lever == "none available"`, and reading them back is what
        # keeps this a report of the planner's reasoning rather than a
        # re-derivation that could drift from it.
        core_verdicts = " | ".join(
            l["verdict"] for l in raw.get("levers", []) if l["reliability"] is None
        )
        if "requires train movements" in core_verdicts:
            reason = REASON_CLASS_D_TRAIN_MOVEMENTS
            detail = ("This activity requires trains to be running, so it cannot "
                      "be performed inside a traffic block at any block length.")
        elif "requires live OHE" in core_verdicts:
            reason = REASON_CLASS_D_LIVE_OHE
            detail = ("This activity requires the overhead line to be live, so it "
                      "cannot be performed inside a power block at any block length.")
        elif levers and not any(l["admissible"] for l in levers):
            reason = REASON_RELIABILITY_BELOW_THETA
            best = max((l for l in levers if l["reliability"] is not None),
                       key=lambda l: l["reliability"], default=None)
            detail = (
                f"No permitted block length reaches the reliability floor "
                f"theta = {theta}."
                + (f" The best available was {best['lever']} at "
                   f"{best['reliability']:.3f}." if best else "")
            )
        else:
            reason = REASON_NO_ADMISSIBLE_COLUMN
            detail = ("No admissible column exists for this job under the current "
                      "constraints.")

        evidence = [{
            "code": "NO_ADMISSIBLE_COLUMN",
            "statement": detail,
            "source": "core.explain_refusal (INFEASIBLE branch)",
            "provenance": PROV_ASSUMPTION,
        }]
        for lever in levers:
            if lever["reliability"] is not None:
                evidence.append({
                    "code": "LEVER_TESTED",
                    "statement": (
                        f"{lever['lever']}: modelled reliability "
                        f"{lever['reliability']:.3f} -> {lever['verdict']}."
                    ),
                    "source": "core.reliability_mc",
                    "provenance": PROV_ASSUMPTION,
                })

        return {
            "reason_code": reason,
            "detail": detail,
            "candidate_columns": raw.get("candidate_columns", 0),
            "levers": levers,
            "evidence": evidence,
        }

    def _shape_outbid(self, raw, internals) -> dict[str, Any]:
        would = raw.get("would_go_in")
        price = raw.get("price_of_forcing")
        displaced = list(raw.get("displaced", []))

        # core's `displaced` is the ENTIRE deferred set of the forced re-solve,
        # minus the forced job -- so it includes every job that was already
        # deferred in the baseline plan anyway. Reporting that count as
        # "displaced by this job" would materially overstate the consequence
        # (46 jobs, when 46 were already deferred before). The jobs actually
        # pushed out are the ones deferred in the forced plan but NOT in the
        # baseline. Both are returned: `displaced` keeps the contract's field,
        # `newly_displaced` is the honest answer to "what would this cost".
        baseline_deferred = set(internals.deferred_job_ids)
        newly_displaced = sorted(set(displaced) - baseline_deferred)

        if newly_displaced:
            consequence = (
                f" and push {len(newly_displaced)} job(s) out of the plan that "
                f"are currently scheduled: {', '.join(newly_displaced)}."
            )
        else:
            consequence = (
                ", without pushing any currently scheduled job out -- the cost is "
                "in traffic delay and overrun risk rather than in displaced work."
            )
        detail = (
            f"Admissible placements exist, but inserting this job would raise the "
            f"plan objective by {price} weighted train-minutes" + consequence
        )

        return {
            "reason_code": REASON_OUTBID,
            "detail": detail,
            "candidate_columns": raw.get("candidate_columns", 0),
            "price_of_forcing": price,
            "would_go_in": would,
            "displaced": displaced,
            "newly_displaced": newly_displaced,
            "cheapest_admissible_columns": raw.get("cheapest_admissible_columns", []),
            "levers": [],
            "evidence": [
                {
                    "code": "PRICED_FORCED_INSERTION",
                    "statement": (
                        f"Forcing this job into the plan costs {price} weighted "
                        f"train-minutes against the baseline objective of "
                        f"{internals.objective:.1f}."
                    ),
                    "source": "core.explain_refusal (OUTBID branch, re-solve)",
                    "provenance": PROV_ASSUMPTION,
                },
                {
                    "code": "DISPLACEMENT",
                    "statement": (
                        f"Currently-scheduled work that would be pushed out: "
                        f"{', '.join(newly_displaced)}."
                        if newly_displaced else
                        "No currently-scheduled job would be pushed out."
                    ),
                    "source": (
                        "core.explain_refusal (OUTBID branch, re-solve), compared "
                        "against the baseline plan's deferred set"
                    ),
                    "provenance": PROV_ASSUMPTION,
                },
            ],
        }
