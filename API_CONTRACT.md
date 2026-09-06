# BlockPlan API contract — Phase 0 draft

Status: DRAFT for review. Nothing here is implemented. This document is the
Phase 0 deliverable — the agreed JSON shape of all nine endpoints — so the
frontend can be built against `plan.json` while the backend does not yet
exist, per the project roadmap.

Nine endpoints, no more, per the frozen decision. Field names below are taken
directly from the real column headers in
`blockplan-dataset\dataset\processed\*.csv` and the real dataclasses in
`blockplan\core.py` (`Section`, `Train`, `Job`, `Window`, `Column`, and the
return shapes of `solve()`, `evaluate()`, `explain_refusal()`) — not invented
names. Where a response field is renamed from its CSV/core.py name, the source
is noted.

All responses are `application/json`. All errors follow the shape:

```json
{ "detail": "human-readable message" }
```

(FastAPI's default `HTTPException` shape — no custom envelope.)

---

## 1. `GET /corridor`

Static corridor geography. Computes nothing; reads `context/` once at
startup.

**Query params:** none.

**Response:**

```json
{
  "stations": [
    {
      "station_code": "JTJ",
      "station_name": "JOLARPETTAI",
      "latitude": 12.560852,
      "longitude": 78.57782,
      "seq": 0,
      "is_junction": false
    }
  ],
  "sections": [
    {
      "section_id": "JTJ-TPT-UP",
      "from_station_code": "JTJ",
      "to_station_code": "TPT",
      "line": "UP",
      "length_km": 7.471,
      "tracks": 2,
      "electrified": true,
      "is_single": false,
      "headway_min": 4,
      "degraded_factor": 2.5
    }
  ]
}
```

27 stations, 52 section-lines. `is_junction`, `electrified`, `is_single` are
CSV `0/1` ints converted to JSON booleans by Pydantic; every other field is a
direct passthrough of the CSV column of the same name.

---

## 2. `GET /scenarios`

The eight scenarios and their declared parameters. Reads
`dataset/scenarios/scenarios.csv` and `scenario_jobs_manifest.csv`.

**Response:**

```json
{
  "scenarios": [
    {
      "name": "NORMAL_TRAFFIC",
      "demand_scale": 1.0,
      "freight_scale": 1.0,
      "uncertainty_scale": 1.0,
      "urgency_shift": 0,
      "backlog": 1.0,
      "extra_passenger_scale": null,
      "cancel_window_fraction": null,
      "note": "Baseline. Real timetable, ordinary maintenance load.",
      "realised_job_count": 175
    }
  ]
}
```

`realised_job_count` comes from `scenario_jobs_manifest.csv` (`generated_jobs`
column), not from the scenario declaration — the two can differ because
demand is Poisson-realised, not fixed.

---

## 3. `GET /demand`

Maintenance job demand for one scenario. Reads
`dataset/scenarios/jobs/jobs_<SCENARIO>.csv`.

**Query params:** `scenario` (required, one of the 8 names).

**Response:**

```json
{
  "scenario": "NORMAL_TRAFFIC",
  "jobs": [
    {
      "job_id": "J00016",
      "dept": "ENGG",
      "activity": "THROUGH_TAMPING",
      "section_id": "KEY-KNNT-UP",
      "km_from": 0.539,
      "km_to": 2.586,
      "needs_T": true,
      "needs_P": false,
      "needs_D": false,
      "needs_train_movements": false,
      "needs_live_ohe": false,
      "duration_mean_min": 61.9,
      "duration_sd_min": 11.2,
      "due_day": 0,
      "criticality": 1.751,
      "priority": "URGENT",
      "uncertainty_level": "MEDIUM",
      "resources": ["TAMPER_1"]
    }
  ]
}
```

Field names match `jobs_<SCENARIO>.csv` columns directly, with `T/P/D` flags
converted to booleans and `resources` (a `|`-joined or single string in the
CSV) split into a JSON array. `priority` and `uncertainty_level` are carried
through as informational/UI labels only — per the dataset's own documentation
they are derived, not consumed by the optimiser, and the API must not imply
otherwise.

---

## 4. `GET /traffic`

Train movements for the timeline's traffic-density background. Reads
`dataset/processed/movements.csv`, filtered by scenario-specific adjustments
(`add_peak_passenger_traffic`, `apply_freight_scenario`) already implemented
in `blockplan_adapter.py`.

**Query params:** `scenario` (required), `section_id` (optional — omit for
all sections).

**Response:**

```json
{
  "scenario": "NORMAL_TRAFFIC",
  "movements": [
    {
      "train_number": "56839",
      "train_class": "PASSENGER",
      "from_code": "JTJ",
      "to_code": "TPT",
      "direction": "DN",
      "enter_min": 920,
      "is_synthetic": false
    }
  ]
}
```

`is_synthetic` must be surfaced and must never be hidden or defaulted away —
it is how the frontend (and a judge) can tell real timetable movements from
the synthetic freight paths.

---

## 5. `POST /plan` — the one that matters

Runs the full pipeline under the planning lock: `expand_mandatory_pairings →
enumerate_bundles → build_columns → solve → evaluate`.

**Request:**

```json
{
  "scenario": "NORMAL_TRAFFIC",
  "horizon_days": 14,
  "theta": 0.90,
  "max_bundle_size": 5,
  "mc_samples": 4000,
  "seed": 20260905
}
```

All six fields required — no server-side defaults for solve-affecting
parameters, because a hidden default is exactly the kind of thing that makes
two "identical" requests produce different plans (per the memory document's
instruction that `mc_samples` must be pinned in every request). Pydantic
rejects `theta` outside `(0, 1)`, `horizon_days < 1`, or an unknown
`scenario` value with `422` before any of this reaches `core.py`.

**Response:**

```json
{
  "plan_id": "a3f9c1e2b7d4",
  "scenario": "NORMAL_TRAFFIC",
  "horizon_days": 14,
  "theta": 0.90,
  "status": "OPTIMAL",
  "objective": 337.8,
  "blocks": [
    {
      "block_id": "B0003",
      "section_id": "KEY-KNNT-UP",
      "day": 3,
      "start_min": 540,
      "length": 150,
      "end_min": 690,
      "reliability": 0.93,
      "traffic_cost": 41.2,
      "exp_overrun_cost": 3.1,
      "dept_mix": ["ENGG", "SNT", "TRD"],
      "job_ids": ["J00016", "J00016_C_SNT", "J00016_C_TRD"]
    }
  ],
  "deferred": [
    {
      "job_id": "J00172",
      "dept": "ENGG"
    }
  ],
  "summary": {
    "blocks": 140,
    "jobs_done": 237,
    "jobs_deferred": 1,
    "traffic_cost": 299.2,
    "traffic_per_job": 1.3,
    "exp_overrun_cost": 38.6,
    "cross_dept_blocks": 51,
    "cross_dept_share": 0.364,
    "min_reliability": 0.90,
    "mean_reliability": 0.99,
    "block_utilisation": 0.68
  },
  "stage_timings_s": {
    "load_config": 0.0,
    "expand_pairings": 0.0,
    "enumerate_bundles": 0.01,
    "build_columns": 0.6,
    "solve": 3.9,
    "total_warm": 4.5
  }
}
```

- `blocks[].job_ids` and `dept_mix` are derived from the `Column`/`Job`
  objects (`Column.job_ids`, plus each job's `dept`), not new concepts.
- `summary` is `core.evaluate()`'s return dict, field-for-field with no
  renaming, minus its `method` key (the label `evaluate()` was called with,
  constant at `"OURS"` for every plan and therefore noise on the wire).
- `deferred` only lists job id + dept here; the *reason* is deliberately not
  duplicated into this response — that is what `/explain` is for, and
  computing it costs ~4s per job (the OUTBID branch), so `/plan` must not pay
  that cost for every deferred job on every request.
- `status` can be `OPTIMAL`, `FEASIBLE`, or (only if every job is deferred and
  the objective is the all-deferral cost) still `OPTIMAL` with an empty
  `blocks` list and `200` — this is a **valid answer**, not a failure (see
  Errors below).

---

## 6. `GET /plan/{plan_id}`

Re-serve an already-computed plan without recomputing. Reads the in-memory
plan cache only.

**Response:** identical shape to `POST /plan`'s response.

**404** if `plan_id` is not in the cache (e.g. server restarted, or a
copy-pasted stale id).

---

## 7. `GET /plan/{plan_id}/block/{block_id}`

Bundle detail for the Why panel. Reads the plan cache; recomputes nothing
(reliability is already known — it was cached in `build_columns`).

**Response:**

```json
{
  "plan_id": "a3f9c1e2b7d4",
  "block_id": "B0003",
  "section_id": "KEY-KNNT-UP",
  "day": 3,
  "start_min": 540,
  "length": 150,
  "reliability": 0.93,
  "jobs": [
    {
      "job_id": "J00016",
      "dept": "ENGG",
      "activity": "THROUGH_TAMPING",
      "is_companion": false,
      "duration_mean_min": 61.9,
      "duration_sd_min": 11.2
    },
    {
      "job_id": "J00016_C_TRD",
      "dept": "TRD",
      "activity": "OHE_HEIGHT_ADJUSTMENT",
      "is_companion": true,
      "parent_id": "J00016",
      "duration_mean_min": 25,
      "duration_sd_min": 8
    },
    {
      "job_id": "J00016_C_SNT",
      "dept": "SNT",
      "activity": "SNT_ASSOCIATION",
      "is_companion": true,
      "parent_id": "J00016",
      "duration_mean_min": 15,
      "duration_sd_min": 5
    }
  ],
  "departmental_chains": [
    { "dept": "ENGG", "mean_min": 61.9, "sd_min": 11.2, "closing_mean_min": 12.0, "closing_sd_min": 4.0 },
    { "dept": "TRD",  "mean_min": 25.0, "sd_min": 8.0,  "closing_mean_min": 15.0, "closing_sd_min": 5.0 },
    { "dept": "SNT",  "mean_min": 15.0, "sd_min": 5.0,  "closing_mean_min": 20.0, "closing_sd_min": 7.0 }
  ],
  "reliability_by_allowed_length": {
    "120": 0.71,
    "150": 0.93,
    "240": 0.99
  }
}
```

`departmental_chains` and `reliability_by_allowed_length` are what the Why
panel's three-chain diagram draws directly — this is
`reliability_closed_form`'s per-department `(mean, sd)` pair plus the fixed
`CLOSING` constants, evaluated at each `ALLOWED_BLOCK_LENGTHS` /
`EXCEPTIONAL_LENGTH` value. Cheap (closed-form, not Monte Carlo) because this
is an explanatory view, not a re-solve.

**404** if `plan_id` or `block_id` is unknown.

---

## 8. `POST /plan/{plan_id}/explain/{job_id}`

Wraps `explain_refusal`. Two genuinely different response shapes depending on
verdict — the frontend must branch on `verdict`, not guess from field
presence.

**INFEASIBLE** (cost ≈ 0s):

```json
{
  "job_id": "J00006",
  "verdict": "INFEASIBLE",
  "candidate_columns": 0,
  "levers": [
    {
      "lever": "none available",
      "reliability": null,
      "verdict": "activity requires live OHE; it cannot be done inside a power block"
    }
  ]
}
```

**OUTBID** (cost ≈ 4s — re-solves with the job forced in):

```json
{
  "job_id": "J00172",
  "verdict": "OUTBID",
  "candidate_columns": 6,
  "price_of_forcing": 14.7,
  "would_go_in": {
    "day": 9,
    "start": 300,
    "length": 120,
    "with": [],
    "reliability": 0.95,
    "traffic_cost": 22.4
  },
  "displaced": ["J00203"],
  "cheapest_admissible_columns": [
    { "day": 9, "start": 300, "len": 120, "R": 0.95, "traffic": 22.4, "bundle": ["J00172"] }
  ]
}
```

Field names are a direct passthrough of `explain_refusal()`'s actual return
dict in `core.py` §10 — not renamed, so there is no translation layer to keep
in sync.

**Response must include a `verdict` field before any expensive computation is
described**, so the frontend can show a spinner only for `OUTBID` (§8 of the
memory document is explicit that conflating the two costs is a UX mistake,
not just a backend one).

---

## 9. `GET /comparison`

Serves the three frozen benchmark artefacts as-is. No computation — this
endpoint is a reader, not a runner.

**Response:**

```json
{
  "method_comparison": [
    {
      "method": "B0 Dept-wise, no reliability",
      "blocks": 161,
      "jobs_done": 161,
      "jobs_deferred": 14,
      "traffic_cost": 391.4,
      "traffic_per_job": 2.4,
      "exp_overrun_cost": 66.8,
      "cross_dept_blocks": 31,
      "cross_dept_share": 0.193,
      "mean_reliability": 0.99,
      "min_reliability": 0.74,
      "block_utilisation": 0.312
    }
  ],
  "execution_scoring_summary": [
    {
      "method": "B0 Dept-wise, no reliability",
      "blocks": 161,
      "realisations": 30,
      "block_realisations": 4830,
      "plan_observed_rate_with_penalty": 0.995,
      "worst_block_observed_with_penalty": 0.83,
      "max_observed_overrun_min_with_penalty": 38.7,
      "mean_abs_error_with_penalty": 0.004
    }
  ],
  "benchmark_results": [
    {
      "scenario": "NORMAL_TRAFFIC",
      "status": "OPTIMAL",
      "jobs_after_pairing": 238,
      "bundles": 449,
      "windows": 11648,
      "columns": 16746,
      "blocks": 140,
      "deferred": 1,
      "cross_department_pct": 0.364,
      "traffic_cost": 299.2,
      "avg_reliability": 0.993,
      "min_reliability": 0.901,
      "seconds": 2.08
    }
  ]
}
```

Every number here must match its source CSV byte-for-byte (rounding only
where the CSV itself already rounds) — this is explicitly a reader, and any
rounding invented in the frontend or backend is a Phase 7 test failure by
definition (memory doc §17, Phase 7's "Definition of done").

The full column lists are wider than shown above (`execution_scoring_summary`
alone has 25 columns) — the actual response includes every column from the
three CSVs; the excerpts here only show the columns the Evidence view's first
draft needs. Extending this later is additive, not a contract break.

---

## Error handling (frozen semantics — see memory doc §9)

| Situation | Status |
|---|---|
| `theta` outside `(0,1)`, `horizon_days < 1`, unknown field, wrong type | `422` |
| Unknown scenario name, unknown `plan_id`, unknown `block_id`/`job_id` | `404` |
| No feasible plan — every job deferred | `200`, empty `blocks`, populated `deferred` |
| Solver hits its time limit without proving optimality | `200`, `status: "FEASIBLE"` |
| Malformed job row (`Job.__post_init__` raises) | `500`, exception message surfaced, not swallowed |

**"No feasible plan" is not an error.** A plan with zero blocks and every job
deferred at `theta = 0.99` is the tool working correctly, and must return
`200`.

---

## Open questions for review

1. `POST /plan` is listed as synchronous, ~4.5s warm / ~18s cold. Confirmed
   no polling, no job id + separate status check — the whole roadmap depends
   on this staying a single blocking HTTP call. Please confirm before Phase 1
   starts, since it's the single architectural decision everything else rests
   on.
2. Plan cache key: proposed as a hash of the six request fields
   (`scenario`, `horizon_days`, `theta`, `max_bundle_size`, `mc_samples`,
   `seed`). Two identical requests should hit the cache, not re-solve.
3. `dept_mix` and `job_ids` on `/plan`'s `blocks[]` — confirm this is enough
   for the timeline's first pass, or whether the timeline needs per-job
   `activity` names inline too (would avoid a second round-trip to
   `/plan/{id}/block/{id}` just to label a bar, at the cost of a heavier
   `/plan` response).
