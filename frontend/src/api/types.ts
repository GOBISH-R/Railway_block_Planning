/**
 * Types mirroring API_CONTRACT.md field-for-field. No client-side
 * reshaping happens between these types and the JSON the backend returns --
 * if a field is renamed here, it has drifted from the contract, which is
 * exactly the class of bug the contract exists to prevent.
 */

export type Dept = "ENGG" | "SNT" | "TRD";

export interface Station {
  station_code: string;
  station_name: string;
  latitude: number;
  longitude: number;
  seq: number;
  is_junction: boolean;
}

export interface SectionMeta {
  section_id: string;
  from_station_code: string;
  to_station_code: string;
  line: string;
  length_km: number;
  tracks: number;
  electrified: boolean;
  is_single: boolean;
  headway_min: number;
  track_source?: string;
}

export interface CorridorResponse {
  stations: Station[];
  sections: SectionMeta[];
}

export interface ScenarioRow {
  name: string;
  demand_scale: number;
  freight_scale: number;
  uncertainty_scale: number;
  urgency_shift: number;
  backlog: number;
  extra_passenger_scale: number | null;
  cancel_window_fraction: number | null;
  note: string;
  realised_job_count: number;
}

export interface ScenariosResponse {
  scenarios: ScenarioRow[];
}

export interface DemandJob {
  job_id: string;
  dept: Dept;
  activity: string;
  section_id: string;
  km_from: number;
  km_to: number;
  needs_T: boolean;
  needs_P: boolean;
  needs_D: boolean;
  needs_train_movements: boolean;
  needs_live_ohe: boolean;
  duration_mean_min: number;
  duration_sd_min: number;
  due_day: number;
  criticality: number;
  priority: string;
  uncertainty_level: string;
  resources: string[];
}

export interface DemandResponse {
  scenario: string;
  jobs: DemandJob[];
}

export interface Movement {
  train_number: string;
  train_class: string;
  from_code: string;
  to_code: string;
  direction: string;
  enter_min: number;
  is_synthetic: boolean;
  section_id: string;
}

export interface TrafficResponse {
  scenario: string;
  movements: Movement[];
}

export interface PlanRequest {
  scenario: string;
  horizon_days: number;
  theta: number;
  max_bundle_size: number;
  mc_samples: number;
  seed?: number | null;
}

export interface PlanBlock {
  block_id: string;
  section_id: string;
  day: number;
  start_min: number;
  length: number;
  end_min: number;
  reliability: number;
  traffic_cost: number;
  exp_overrun_cost: number;
  dept_mix: Dept[];
  job_ids: string[];
}

export interface DeferredEntry {
  job_id: string;
  dept: Dept;
}

export interface PlanSummary {
  blocks: number;
  jobs_done: number;
  jobs_deferred: number;
  traffic_cost: number;
  traffic_per_job: number;
  exp_overrun_cost: number;
  cross_dept_blocks: number;
  cross_dept_share: number;
  min_reliability: number;
  mean_reliability: number;
  block_utilisation: number;
}

export interface PlanResponse {
  plan_id: string;
  scenario: string;
  horizon_days: number;
  theta: number;
  status: "OPTIMAL" | "FEASIBLE" | string;
  cache_hit: boolean;
  objective: number;
  blocks: PlanBlock[];
  deferred: DeferredEntry[];
  summary: PlanSummary;
  stage_timings_s: Record<string, number>;
  instance: {
    base_jobs: number;
    jobs_after_pairing: number;
    bundles: number;
    windows: number;
    columns: number;
    mc_samples: number;
    max_bundle_size: number;
    seed: number | null;
  };
}

export interface JobView {
  job_id: string;
  dept: Dept;
  activity: string;
  section_id: string;
  km_from: number;
  km_to: number;
  duration_mean_min: number;
  duration_sd_min: number;
  due_day: number;
  criticality: number;
  protection_required: string[];
  resources: string[];
  is_companion: boolean;
  parent_id: string | null;
  needs_train_movements: boolean;
  needs_live_ohe: boolean;
  provenance: string;
}

export interface DepartmentalChain {
  dept: Dept;
  mean_min: number;
  sd_min: number;
  z: number;
  phi: number;
}

export interface Evidence {
  code: string;
  statement: string;
  source: string;
  provenance: string;
}

export interface MandatoryPairing {
  parent_job_id: string;
  parent_activity: string;
  companion_job_id: string;
  compelled_dept: Dept;
  companion_activity: string;
  must_follow_parent: boolean;
  source: string;
  confidence: number;
  provenance: string;
}

export interface PairConstraint {
  job_a: string;
  job_b: string;
  compatible: boolean;
  same_section_line: boolean;
  footprints_overlap: boolean;
  rule_paired: boolean;
  shared_exclusive_resource: string[];
  incompatibility_reason: string | null;
}

export interface BlockExplanation {
  plan_id: string;
  block_id: string;
  scenario: string;
  decision_status: "SCHEDULED";
  reason_code: string;
  section_id: string;
  section: SectionMeta;
  day: number;
  start_min: number;
  end_min: number;
  length: number;
  reliability: number;
  jobs: JobView[];
  departments: Array<{
    dept: Dept;
    job_count: number;
    work_minutes: number;
    closing_chain_mean_min: number;
    closing_chain_sd_min: number;
  }>;
  departmental_chains: DepartmentalChain[];
  envelope: {
    allowed_block_lengths: number[];
    exceptional_length: number;
    selected_length: number;
    is_exceptional_length: boolean;
    work_minutes: number;
    utilisation: number;
    protection_regimes: string[];
  };
  reliability_by_allowed_length: Record<string, number>;
  constraints: {
    applied_theta: number;
    meets_theta: boolean;
    max_span_km: number;
    bundle_span_km: number;
    mandatory_pairings: MandatoryPairing[];
    pairwise: PairConstraint[];
  };
  objective: {
    traffic_cost: number;
    expected_overrun_cost: number;
    column_total_cost: number;
    plan_objective: number;
    units: string;
  };
  evidence: Evidence[];
  provenance: Record<string, string>;
  computation: Record<string, unknown>;
}

export type RefusalVerdict = "INFEASIBLE" | "OUTBID" | "INFEASIBLE_WHEN_FORCED";

export interface Lever {
  lever: string;
  reliability: number | null;
  admissible: boolean;
  verdict: string;
}

export interface JobExplanation {
  plan_id: string;
  job_id: string;
  scenario: string;
  decision_status: "SCHEDULED" | "DEFERRED";
  applied_theta: number;
  job: JobView;
  evidence: Evidence[];
  computation: Record<string, unknown>;

  // SCHEDULED
  reason_code?: string;
  scheduled_in?: {
    block_id: string;
    section_id: string;
    day: number;
    start_min: number;
    length: number;
    reliability: number;
    shares_block_with: string[];
    departments_in_block: Dept[];
  };
  objective?: Record<string, number | string>;
  alternative_optima_exist?: boolean;
  caveat?: string;

  // DEFERRED
  verdict?: RefusalVerdict;
  detail?: string;
  candidate_columns?: number;
  levers?: Lever[];
  price_of_forcing?: number | null;
  would_go_in?: {
    day: number;
    start: number;
    length: number;
    with: string[];
    reliability: number;
    traffic_cost: number;
  } | null;
  displaced?: string[];
  newly_displaced?: string[];
  cheapest_admissible_columns?: Array<Record<string, unknown>>;
  provenance?: Record<string, string>;
}

export interface ComparisonResponse {
  method_comparison: Array<Record<string, number | string>>;
  execution_scoring_summary: Array<Record<string, number | string>>;
  benchmark_results: Array<Record<string, number | string>>;
}

export interface ApiErrorBody {
  detail: string;
}
