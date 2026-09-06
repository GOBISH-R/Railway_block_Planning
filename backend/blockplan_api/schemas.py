"""Pydantic v2 request/response models for the explanation endpoints.

These pin the wire format described in API_CONTRACT.md. Where Phase 2 adds
fields the contract did not previously specify, the contract document was
extended alongside -- the additions are a superset, so nothing already
documented changed shape.

Models are permissive about extra keys on the way OUT (the service is the
source of truth for its own payload) but strict on the way IN: a request
carrying an unknown field is a client bug and is rejected with 422 rather than
silently ignored, which is the whole point of validating before anything
reaches frozen code.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# -- requests --------------------------------------------------------------

class PlanRequestModel(BaseModel):
    """POST /plan body.

    Every solve-affecting parameter is explicit. mc_samples in particular must
    be pinned by the caller: the block count genuinely differs between 1500 and
    4000 samples because different Monte Carlo estimates cross theta
    differently. That is expected behaviour, but only if it is stated.
    """

    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(..., min_length=1)
    horizon_days: int = Field(14, ge=1, le=60)
    theta: float = Field(0.90, gt=0.0, lt=1.0)
    max_bundle_size: int = Field(5, ge=1, le=10)
    mc_samples: int = Field(1500, ge=1, le=100_000)
    seed: int | None = None


# -- shared response pieces ------------------------------------------------

class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class JobView(_Loose):
    job_id: str
    dept: Literal["ENGG", "SNT", "TRD"]
    activity: str
    section_id: str
    km_from: float
    km_to: float
    duration_mean_min: float
    duration_sd_min: float
    due_day: int
    criticality: float
    protection_required: list[str]
    resources: list[str]
    is_companion: bool
    parent_id: str | None = None
    needs_train_movements: bool
    needs_live_ohe: bool
    provenance: str


class DepartmentalChain(BaseModel):
    """One department's hand-back chain against the block envelope."""

    dept: Literal["ENGG", "SNT", "TRD"]
    mean_min: float
    sd_min: float
    z: float
    phi: float


class Evidence(BaseModel):
    """A single supporting fact, traceable to where it came from."""

    code: str
    statement: str
    source: str
    provenance: str


class MandatoryPairing(BaseModel):
    parent_job_id: str
    parent_activity: str
    companion_job_id: str
    compelled_dept: Literal["ENGG", "SNT", "TRD"]
    companion_activity: str
    must_follow_parent: bool
    source: str
    confidence: float
    provenance: str


class PairConstraint(BaseModel):
    job_a: str
    job_b: str
    compatible: bool
    same_section_line: bool
    footprints_overlap: bool
    rule_paired: bool
    shared_exclusive_resource: list[str]
    incompatibility_reason: str | None = None


# -- block explanation -----------------------------------------------------

class BlockExplanation(_Loose):
    """GET /plan/{plan_id}/block/{block_id}."""

    plan_id: str
    block_id: str
    scenario: str
    decision_status: Literal["SCHEDULED"]
    reason_code: str
    section_id: str
    section: dict[str, Any]
    day: int
    start_min: int
    end_min: int
    length: int
    reliability: float
    jobs: list[JobView]
    departments: list[dict[str, Any]]
    departmental_chains: list[DepartmentalChain]
    envelope: dict[str, Any]
    reliability_by_allowed_length: dict[str, float]
    constraints: dict[str, Any]
    objective: dict[str, Any]
    evidence: list[Evidence]
    provenance: dict[str, Any]
    computation: dict[str, Any]


# -- job explanation -------------------------------------------------------

class JobExplanation(_Loose):
    """POST /plan/{plan_id}/explain/{job_id}.

    Two genuinely different shapes share this model, and a client must branch on
    `decision_status` and then on `verdict` rather than guessing from which
    fields happen to be present:

      SCHEDULED  -> scheduled_in, objective
      DEFERRED   -> verdict INFEASIBLE (levers) | OUTBID (price_of_forcing,
                    would_go_in, displaced) | INFEASIBLE_WHEN_FORCED
    """

    plan_id: str
    job_id: str
    scenario: str
    decision_status: Literal["SCHEDULED", "DEFERRED"]
    applied_theta: float
    job: JobView
    evidence: list[Evidence]
    computation: dict[str, Any]

    # SCHEDULED
    reason_code: str | None = None
    scheduled_in: dict[str, Any] | None = None
    objective: dict[str, Any] | None = None
    alternative_optima_exist: bool | None = None
    caveat: str | None = None

    # DEFERRED
    verdict: Literal["INFEASIBLE", "OUTBID", "INFEASIBLE_WHEN_FORCED"] | None = None
    detail: str | None = None
    candidate_columns: int | None = None
    levers: list[dict[str, Any]] | None = None
    price_of_forcing: float | None = None
    would_go_in: dict[str, Any] | None = None
    # `displaced` is core's raw field: every job deferred in the forced re-solve,
    # which includes those already deferred in the baseline. `newly_displaced` is
    # the subset actually pushed out by this insertion -- the one to show a user.
    displaced: list[str] | None = None
    newly_displaced: list[str] | None = None
    cheapest_admissible_columns: list[dict[str, Any]] | None = None
    provenance: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    detail: str
