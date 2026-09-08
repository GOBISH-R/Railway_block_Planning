# BlockPlan — Master Technical Documentation

**Project:** AI-Powered Automatic Block Planning to Maximise Asset Availability
(SIH 2026, PS 26027) — Jolarpettai–Salem–Erode corridor
**Repository:** `GOBISH-R/Railway_block_Planning`
**Audience:** anyone from "never seen this repo" to a technical jury.

---

## How to read this document

Every figure below was read out of the repository on 2026-09-08 — from the
CSVs, the YAML configs, `core.py`, the FastAPI route table and the frontend
source. Where a number could not be verified it is not stated.

Three provenance classes are used throughout, and they are the same ones the
code uses at every constant's definition:

| Tag | Meaning |
|---|---|
| **RULE** | Traced to an Indian Railways manual. The citation is in `rules.yaml`. |
| **DECL** | A modelling parameter we chose. Editable. **Not a fact.** Lives in `assumptions.yaml`. |
| **SYNTH** | Generated instance data. **Not Indian Railways data.** |

**The single most important sentence in this document:** the infrastructure,
the station list and the passenger timetable are real public data
(DataMeet / Indian Railways, CC0). The maintenance jobs, the block requests,
the freight paths and the execution outcomes are **synthetic** — generated from
documented distributions and labelled as such in
`dataset/metadata/manifest.json`. Never present the synthetic half as
operational railway data, and never present the real half as synthetic. Both
directions of that error are damaging.

---

## Part 0 — The problem, and the shape of the answer

### 0.1 What a maintenance block is

Track wears out. Rails develop internal cracks, ballast fouls and loses its
drainage, track geometry drifts out of alignment, overhead contact wire sags,
point machines fall out of adjustment. Fixing any of it means people and heavy
machines standing on the track — which means stopping the trains. That
protected window is a **maintenance block**.

Three separate things can be withdrawn, and they are not the same thing:

| Regime | What it grants | Source (RULE) |
|---|---|---|
| **T** — traffic block | Bar on trains entering the block section | IR General Rules 15.08, 15.09 |
| **P** — power block | OHE de-energised, isolated and earthed; permit-to-work ETR-3 per party | AC Traction Manual Vol.II Pt.I Ch.VI; ACTM Ch.17 |
| **D** — S&T disconnection | Signalling equipment disconnected from interlocking | GR 15.08 + zonal Joint Procedure Order |

A power block does **not** stop trains — diesel traction may still pass under
caution. That distinction matters: it is why some work can share a window with
traffic and some cannot.

### 0.2 The dilemma

- Every minute of block delays trains, and the delay cascades.
- Every deferred job raises the risk of a rail fracture, a speed restriction,
  or worse.
- Blocks are currently assembled department by department. Three departments
  wanting the same kilometre of track ask three times, get three separate
  possessions, and the line is withdrawn three times over.

### 0.3 The insight this project is built on

Some maintenance activities **compel** another department's attendance — that
is a rule in the manuals, not our idea. Tamping a track alters its level, and
ACTM Ch.17 requires due notice to OHE staff before any alteration to alignment
or level. So a tamping job *already implies* an overhead-line job.

If the rule already couples them, plan them in **one** block instead of three.
The hard part is not the coupling — it is proving the combined block still
hands back on time, because now three independent departments have to finish,
and the block ends when the **slowest** of them does.

That is the whole project: bundle rule-coupled work into shared blocks, and
constrain each bundle to a minimum probability of on-time hand-back.

### 0.4 Pipeline

```
   REAL PUBLIC DATA                    SYNTHETIC (generated, labelled)
   stations, sections, timetable       maintenance jobs, block requests,
   (DataMeet / IR, CC0)                freight paths, execution outcomes
            |                                       |
            +------------------+--------------------+
                               v
                    RULE EXPANSION  (pairing_rules.csv, 6 RULE rows)
                    175 requested jobs -> 238 jobs
                               v
                    BUNDLE ENUMERATION  (compatibility graph)
                    238 jobs -> 449 bundles
                               v
                    WINDOW GENERATION + TRAFFIC PRICING
                    11,648 candidate windows
                               v
                    MONTE CARLO RELIABILITY  (per bundle x block length)
                    keep only P(hand back on time) >= theta
                    449 bundles x windows -> 16,746 columns
                               v
                    CP-SAT SET PACKING  (OR-Tools, deterministic)
                    choose columns; objective 337.4; 140 blocks
                               v
                    PLAN + EXPLANATION  (FastAPI)  ->  React frontend
```

---

## Part 1 — The corridor

Jolarpettai Junction (JTJ) to Erode Junction (ED), Southern Railway.

| Fact | Value | Source |
|---|---|---|
| Corridor length | **182.0 km** (summed over the 26 UP section-lines) | real |
| Stations | **27**, JTJ → ED | real |
| Junctions | **4** — TPT, MGSJ, SA, ED | real (`is_junction` in `stations.csv`) |
| Section-lines | **52** = 26 UP + 26 DN | real |
| Trains | **108**, all real timetable entries | real |
| Train classes | EXPRESS 74, SUPERFAST 28, PASSENGER 4, MAIL 2 | real |
| Movements | **2,978** total = **2,568 real passenger** + **410 synthetic freight** | mixed — see below |

Two things worth getting right, because they are easy to state wrongly:

- **JTJ is the corridor origin but is not flagged as a junction** in the data.
  The four junction flags are TPT, MGSJ, SA and ED. If you say "JTJ, TPT, SA,
  ED" you have named a station the dataset does not mark and omitted one it
  does.
- **There are no Vande Bharat, Rajdhani or Shatabdi services in this data.**
  The corridor's real timetable is Express and Superfast dominated. The
  train-weight table in `assumptions.yaml` *has* rows for those classes so the
  model generalises, but they match nothing here.

Each direction is planned separately — a block on JTJ→TPT UP does not withdraw
JTJ→TPT DN. That is why the unit throughout is the **section-line**, not the
section.

### Why freight is synthetic

CAG Report 45/2018 Ch.3 records that goods trains run "without any scheduled
timing." Public timetables therefore contain almost no freight. Freight here is
generated (mean 8 trains/day/section, sd 3, with an hourly weight profile) and
is the largest single synthetic component of the traffic layer. It is labelled
`FREIGHT` in `movements.csv` and is exactly the 410 rows above.

---

## Part 2 — Repository anatomy

```
D:/SIH2026/
├── CLAUDE.md                  freeze rules — read before editing anything
├── API_CONTRACT.md            the REST contract (frontend is built against it)
├── DEMO.md                    demo script, judge Q&A, readiness checklist
├── run.py                     one command: builds the frontend, serves both
├── plan.json                  Phase-0 mock fixture, used only by a contract test
│
├── Dataset/                   FROZEN. Holds CODE as well as data.
│   ├── blockplan/                     the standalone analytical core
│   │   ├── core.py                    44,044 bytes, 12 numbered sections
│   │   ├── demo.py / dense.py         runnable standalone instances
│   │   ├── ablation.py                does the reliability constraint bite?
│   │   ├── pairing_rules.csv          READ by demo.py and dense.py
│   │   └── jobs/sections/trains.csv   EXPORTS, not inputs — nothing reads them
│   └── blockplan-dataset/
│       ├── config/*.yaml              rules (RULE) + assumptions (DECL)
│       ├── src/blockplan_adapter.py   the ten loaders, reused verbatim
│       ├── src/dsgen/                 the generators that built the dataset
│       ├── src/generate_*.py          dataset + scenario job builders
│       └── dataset/
│           ├── processed/*.csv        the planning inputs
│           ├── scenarios/             8 scenario job sets + frozen benchmarks
│           └── metadata/manifest.json provenance of every table
│
├── backend/
│   ├── blockplan_api/app.py           FastAPI app; static mount registered LAST
│   ├── blockplan_service/             planning service, windows cache, explain
│   ├── blockplan_db/                  PostgreSQL: schema, loader, plan store
│   ├── blockplan_ml/                  LightGBM duration model (default OFF)
│   ├── blockplan_ingest/              TMS/SMMS/TDMS feed adapters (default OFF)
│   └── tests/                         406 tests
│
└── frontend/                    React 19 + TypeScript + Vite
    └── src/components/          Overview, Timeline, Corridor, WhyPanel, Shell
```

### `Dataset/` is not deletable, and PostgreSQL does not replace it

This trips people up, so it is stated plainly:

1. **It contains the optimiser.** `blockplan_service/paths.ensure_import_paths()`
   puts `Dataset/blockplan` and `Dataset/blockplan-dataset/src` on `sys.path`.
   `core.solve` resolves to `Dataset/blockplan/core.py`. A database holds rows,
   not `solve()`.
2. **PostgreSQL mode still goes through it.** `DatabaseDataSource` does not
   stream rows into objects — it *materialises* the snapshot back out to a
   directory of CSVs and hands that directory to the same adapter loaders.
   Reason: `load_trains()` derives each Train id from the row's position in the
   file, so a reimplementation that missed that would silently change the plan.
3. **CSV is the default.** `BLOCKPLAN_DATA_SOURCE` unset resolves to `csv`.
   `python run.py` must work on a machine that has never installed PostgreSQL.

The database is a copy of the dataset plus a place to persist plans and
approvals. It is not a substitute for the folder.

---

## Part 3 — The frozen core (`Dataset/blockplan/core.py`)

44,044 bytes, SHA-256 pinned in `blockplan_service/paths.py` and asserted by
`tests/test_frozen_artifacts.py`. Twelve numbered sections, each naming the
production module it would become:

| # | Section | Becomes |
|---|---|---|
| 1 | Data model | `model.py` |
| 2 | Mandatory pairings | `rules.py` |
| 3 | Compatibility engine | `compat.py` |
| 4 | Bundle enumeration | `bundles.py` |
| 5 | Traffic disruption cost | `traffic.py` |
| 6 | Hand-back reliability | `reliability.py` |
| 7 | Window generation | `windows.py` |
| 8 | Column construction | `columns.py` |
| 9 | Selection (CP-SAT) | `solver.py` |
| 10 | Refusal explanation | `explain.py` |
| 11 | Baselines | `baselines.py` |
| 12 | Evaluation | `evaluate.py` |

**It reads exactly one file.** `core.py` contains a single `open()` call, in
`load_pairing_rules()`. Everything else is passed in as Python objects. It has
no database driver, no HTTP client, and no ML dependency — which is what makes
it runnable standalone and what makes freezing it meaningful.

**Why it is frozen:** every benchmark number in this project was produced by
this exact file. Editing it invalidates all of them. See `CLAUDE.md`.

---

## Part 4 — The data tables

`Dataset/blockplan-dataset/dataset/processed/`:

| File | Rows | What it is | Provenance |
|---|---|---|---|
| `stations.csv` | 27 | code, name, lat/long, zone, state, seq, is_junction | real |
| `sections.csv` | 52 | section_id, from/to, line, length_km, tracks, electrified, headway_min | real |
| `trains.csv` | 108 | number, name, class, direction | real |
| `train_stops.csv` | — | the timetable, station by station | real |
| `movements.csv` | 2,978 | per-section entry times; 2,568 real + 410 SYNTH freight | mixed |
| `activities.csv` | 18 | the activity catalogue: dept, asset, needs_T/P/D | DECL |
| `pairing_rules.csv` | 6 | the mandatory cross-department pairings | **RULE** |
| `resources.csv` | 7 | fleet sizes per resource class | DECL |
| `jobs.csv` | 175 | the maintenance demand | **SYNTH** |
| `block_requests.csv` | 175 | what a department would actually submit | **SYNTH** |
| `execution.csv` | 5,250 | 30 realisations × 175 jobs, for evaluation only | **SYNTH** |
| `execution_companions.csv` | — | the same for rule-generated companions | **SYNTH** |

`execution.csv` is used **only** for scoring, never for planning. It is kept
separate precisely so the planner cannot see the realised durations it is
about to be judged on.

---

## Part 5 — Rule expansion: 175 requests become 238 jobs

The six pairing rules are the core of the contribution. These are the real
ones, verbatim from `pairing_rules.csv` / `rules.yaml`:

| Parent activity | Compels | Companion | Mean ± sd (min) | Ordering | Confidence |
|---|---|---|---|---|---|
| THROUGH_TAMPING | TRD | OHE_HEIGHT_ADJUSTMENT | 25 ± 8 | must follow | 0.90 |
| THROUGH_TAMPING | SNT | SNT_ASSOCIATION | 15 ± 5 | either | 0.88 |
| TURNOUT_TAMPING | SNT | POINT_MOTOR_RESET | 30 ± 10 | must follow | 0.70 |
| TURNOUT_TAMPING | TRD | OHE_HEIGHT_ADJUSTMENT | 20 ± 7 | must follow | 0.70 |
| RAIL_RENEWAL | TRD | TRACTION_BOND_JUMPER | 20 ± 6 | either | 0.90 |
| DEEP_SCREENING | SNT | CABLE_ROD_CLEARANCE | 35 ± 12 | **precedes** | 0.88 |

Each row carries its manual citation and a confidence — a division that
disagrees edits the row and re-plans. The rules are an *editable input*, not a
claim the system makes.

**Three departments, not four:** ENGG 79 jobs, SNT 49, TRD 47 = 175. There is
no separate bridges-and-civil department in this model.

Expansion result: **175 → 238 jobs** (63 rule-generated companions).

---

## Part 6 — Compatibility and bundling

Not everything can share a block. `pairwise_compatible` rejects a pair when:

- their footprints overlap on the same section-line and they are not a
  rule-mandated pair;
- one needs **live OHE** and the other needs a **power block** — contradictory
  states of the same wire (ACTM Ch.17);
- either job needs **train movements** — such a job cannot sit inside a traffic
  block with anything (GR 15.08).

Surviving groups are enumerated as bundles, bounded by
`max_bundle_size: 5` and `max_span_km: 8.0` (both DECL). **238 jobs → 449
bundles.**

### A known behaviour, documented rather than hidden

Class D work (jobs needing train movements) is never bundled *with another
job* — but a **single-job bundle never reaches a pairwise test**, so such a job
can still take a block of its own. On NORMAL_TRAFFIC all 21 Class D jobs are
placed, none deferred, most of them alone in a block whose protection regime is
empty — a "block" in which nothing is actually withdrawn from traffic, though
several are still priced as though one were.

Whether that is a defect depends on an operational question this repository
cannot answer: should work needing no protection consume a block window and be
priced as one? It is flagged in `CLAUDE.md` so nobody discovers it from a
judge.

---

## Part 7 — Windows and traffic pricing

Windows are discrete, not continuous. Only the permitted block lengths are
considered — **150 or 240 minutes** (RULE: IRTMM Ch.5, corroborated by CAG
45/2018 quoting the Railway Board norm of one 4-hour block or two of 2.5 hours
per day).

For each candidate window the traffic cost is the weighted train-minutes of
delay it would cause, using the real movement table and a per-class weight
(DECL — `assumptions.yaml`, *not* railway policy):

```
VANDE_BHARAT/RAJDHANI/SHATABDI 3.0   SUPERFAST 2.2   EXPRESS/MAIL 2.0
PASSENGER/MEMU/DEMU 1.2              FREIGHT 1.0     UNKNOWN 1.5
```

Also DECL: default headway 8 min, single-line headway 15 min, degraded factor
2.5, queue tail 240 min, overrun rate 3.0 weighted train-minutes per minute of
overrun, post-block caution 10 min.

**11,648 candidate windows** on the reference instance.

---

## Part 8 — Hand-back reliability (the chance constraint)

This is where the project's argument actually lives.

A block ends when the **last** department finishes closing out — there is no
Indian Railways equivalent of a single nominated person-in-charge of a
possession. Responsibility is genuinely distributed: the Inspector of Way
superintends engineering work (GR 15.06), a TRD representative must remain on
site for every permit-to-work (ACTM Ch.17), and the Station Master personally
verifies signalling gear and signs the reconnection memo.

So hand-back time is the **maximum over three independent closing chains**
(DECL timings, confidence 0.60 on the structure):

| Dept | Closing time (min) | What it covers |
|---|---|---|
| ENGG | 12.0 ± 4.0 | clear site, withdraw protection, hand back |
| SNT | 20.0 ± 7.0 | reconnect, correspondence test, SM signs memo |
| TRD | 15.0 ± 5.0 | withdraw staff, verify earths, return ETR-3 |

Monte Carlo over the work durations plus these chains gives

$$R = P(\text{hand back within the block length})$$

and only bundles with $R \ge \theta$ become columns.

| Parameter | Value | Class |
|---|---|---|
| `theta` | **0.90** | DECL |
| `kappa` | **0.15** — duration-spread inflation per *extra* department | DECL |
| `lambda_close_min` | **6.0** — extra closing minutes per *extra* department | DECL |
| `mc_samples` | 4,000 default in `core.py`; **1,500** as loaded from config | DECL |

**κ and λ are the entire quantitative content of "more departments means more
risk."** `assumptions.yaml` says so explicitly and asks you to sweep them: if
the conclusion does not survive κ ∈ [0, 0.30], say so. That is the honest
framing to give a jury.

---

## Part 9 — The optimisation model

This is **set packing over pre-enumerated columns**, not interval scheduling.
There are no start-time variables and no interval variables — that work was
already done when the windows were enumerated.

**Decision variable:** one boolean per *column*.

$$x_c \in \{0,1\}, \quad c \in \text{Columns} \;(=\; \text{a bundle placed in a window})$$

16,746 columns on the reference instance.

**Constraints** (all hard; `core.py` §9):

1. **Each job at most once** — $\sum_{c \ni j} x_c \le 1$ for every job $j$.
2. **No two blocks overlap on the same section-line** — the horizon is
   discretised on a 30-minute grid, and for every (section-line, day, slot)
   at most one column may be selected.
3. **An exclusive resource cannot be in two places at once** — the same
   discretisation, keyed by resource class.

**Objective** — one currency throughout: minimise

$$\sum_{c} \text{total\_cost}_c \cdot x_c \;+\; \sum_{j} \text{deferral\_penalty}(j)\,(1 - \text{done}_j)$$

where `total_cost` is the column's traffic cost plus expected overrun cost, and

$$\text{deferral\_penalty}(j) = \frac{\text{criticality}_j \times 100}{1 + \max(0,\ \text{due\_day}_j - \text{horizon\_days})}$$

Costs are scaled by 10 and rounded to integers, because CP-SAT is an integer
solver. Companions carry no separate deferral penalty — they are scheduled with
their parent or not at all.

Note what is **not** in the objective: there is no preferred-slot deviation
term and no freight-cancellation term. Freight is priced through the same
weighted train-minute traffic cost as everything else, at weight 1.0.

### Determinism

```python
solver.parameters.num_workers = 1        # not a portfolio
solver.parameters.random_seed = 1
deterministic_limit = 60.0               # machine-independent work budget
max_time_in_seconds = time_limit_s       # wall-clock safety cap only
```

A wall-clock limit is *not* reproducible: with several workers racing, the same
instance solved twice on the same machine returned 140 blocks once and 137 the
next time. A benchmark whose numbers move between runs cannot support any claim
made from it.

---

## Part 10 — The reference plan, and what is safe to quote

Pinned by `tests/test_reference_plan.py`. Every later phase is gated on it.

| Field | Value |
|---|---|
| `plan_id` | **2db53586d84f** |
| Blocks | **140** |
| Jobs completed | **174** of 175 |
| Jobs deferred | **1** |
| Objective | **337.4** |
| Status | OPTIMAL (proven) |
| Block fingerprint | `6f509bae39c8a032ce99201370b8c8522734a0b247f56bc4d61dcc894600b429` |

### Solution degeneracy — quote these, not those

This instance is **highly degenerate**. Re-solving with the objective pinned at
its proven optimum and the block count then minimised and maximised returns
OPTIMAL at **anywhere from 118 to 153 blocks**, with cross-department share
spanning roughly 27 % to 55 %. Solving with `num_workers=8` instead of 1
returns 142 blocks where deterministic mode returns 140 — same columns, same
objective.

| Invariant across the optimal face — **safe to quote** | Chosen by solver tie-breaking — **do not quote as a result** |
|---|---|
| Objective value | Block count |
| Traffic cost | Cross-department share |
| Expected overrun | Block utilisation |
| Jobs done / deferred | |
| Reliability figures | |

So "cross-department share rose from 18.8 % to 36.4 %" is **not** a measured
effect of the method — it is one arbitrary point in a range of equally optimal
answers. A judge who probes it would be right to. The reliability and
traffic-cost results, which is where the argument actually lives, are
invariant.

Making block count well-defined would need a lexicographic tie-break, which
would change `core.py` and every benchmark number. Not to be done without an
explicit decision.

---

## Part 11 — Baselines and the benchmark

Six methods on the identical NORMAL_TRAFFIC instance, frozen in
`dataset/scenarios/method_comparison.csv`:

| Method | Blocks | Done | Deferred | Traffic cost | Min R |
|---|---|---|---|---|---|
| B0 Dept-wise, no reliability | 161 | 161 | 14 | 391.4 | 0.74 |
| B1 Dept-wise + reliability | 160 | 160 | 15 | 430.8 | 0.90 |
| B2 Fixed-calendar | 105 | 175 | 0 | 743.4 | 0.73 |
| B3 Greedy-earliest | 161 | 161 | 14 | 1750.2 | 0.03 |
| B4 Bundle-only | 138 | 175 | 0 | **272.8** | 0.74 |
| **OURS** | 140 | 174 | 1 | 299.2 | **0.90** |

**Read B4 and OURS together or not at all.** B4 is cheaper on traffic cost
precisely because it admits blocks whose weakest link hands back on time only
74 % of the time, against a 90 % floor. It is not planning better; it is
accepting risk this method refuses.

**Fewer blocks is not better either.** B2 takes the fewest blocks of any
baseline and causes 743.4 weighted delay-minutes doing it — two and a half
times OURS.

> ⚠️ **B4's traffic cost is 272.8.** A figure of 259.8 appears in the project
> memory document's §22.1 and in some earlier slides. It is **superseded** — it
> came from a run whose RNG ordering differed from the one that produced the
> checked-in CSV. The CSV is authoritative. Full reasoning in `CLAUDE.md`.

The benchmark is **not a screen in the app.** The Comparison view was removed
on 2026-09-08. `GET /comparison` still serves these artefacts and
`tests/test_reference_data.py` still pins them, but the running product no
longer argues the method against its baselines — that has to come from the
deck.

---

## Part 12 — Scenarios

Eight, each with its own generated job set in `dataset/scenarios/jobs/`. They
are **generated, not cloned**, and all solve to proven optimality:

`NORMAL_TRAFFIC` · `PEAK_TRAFFIC` · `HEAVY_FREIGHT` ·
`HIGH_DURATION_UNCERTAINTY` · `MAINTENANCE_BACKLOG` ·
`MULTIPLE_DEPARTMENT_REQUESTS` · `URGENT_MAINTENANCE` · `DISRUPTED_OPERATION`

Each is parameterised by `demand_scale`, `freight_scale`, `uncertainty_scale`,
`urgency_shift`, `backlog`, and optionally `extra_passenger_scale` or
`cancel_window_fraction` — see `scenarios.csv`.

`MAINTENANCE_BACKLOG` is the interesting demo: 340 jobs, of which it defers 152
**and tells you which** — a capacity answer a division does not currently have.

---

## Part 13 — Machine learning (optional, default OFF)

`backend/blockplan_ml/` — LightGBM quantile regression estimating `dur_mean`
and `dur_sd` from execution history, so a duration estimate can come from
observed outcomes instead of the catalogue. `core.py` is untouched; only the
origin of two parameter values changes.

**Serving features are 15 job attributes**, and only these:

```
dept, activity, section_id, km_from, km_to, km_span,
needs_T, needs_P, needs_D, needs_train_movements, needs_live_ohe,
due_day, criticality, is_companion, resource_class
```

There is no weather, no crew experience, no machine age, no lighting index in
this project. Those fields do not exist in the dataset.

**The leakage guard** is explicit. These columns are forbidden as features
because they *are* the label in disguise:

```
duration_mean_min, duration_sd_min, duration_min_min, duration_max_min,
minimum_duration_min, requested_duration_min, uncertainty_level
```

### The honest result

**The model does not beat a per-activity lookup on the split that matters.**
Under `GroupKFold(job_id)` — the split that asks "can you predict a job you
have never seen?" — the learned model loses to a simple per-activity table, and
the reasons are structural. Read `backend/blockplan_ml/README.md` before
quoting anything from this work.

This is stated plainly because a jury that discovers it is much worse than a
jury that is told it. It is default-OFF, gated on the frozen plan reproducing
exactly, and `python run.py` works on a machine with neither LightGBM nor
scikit-learn installed.

---

## Part 14 — Backend and the REST API

FastAPI. **These are the actual routes** — no `/api` prefix in a packaged
build, because the frontend is served from the same origin:

| Method | Path | Purpose |
|---|---|---|
| GET | `/corridor` | stations + section-lines |
| GET | `/scenarios` | the eight scenario rows |
| GET | `/demand` | jobs waiting, for one scenario |
| GET | `/traffic` | movement density, optionally per section |
| POST | `/plan` | solve (scenario, theta, horizon) → full plan |
| GET | `/plan/{plan_id}` | retrieve a computed plan |
| GET | `/plan/{plan_id}/block/{block_id}` | why this block: chains, rules, reliability |
| POST | `/plan/{plan_id}/explain/{job_id}` | why this job was refused: INFEASIBLE vs OUTBID |
| GET | `/comparison` | the three frozen benchmark artefacts |
| GET | `/health` | data source, duration source, asset weighting, cache sizes |

There is no `/api/timetable`, no `/api/plan/latest`, no `/api/scenarios/run`
and no `/api/approvals`. **There is no approval workflow in the product.**

Two packaging details that had to be right:

1. **The API base URL is environment-conditional** (`frontend/src/api/client.ts`):
   `/api` in dev (Vite proxies it), empty in a production build. Get it
   backwards and the packaged app 404s on every call while working fine in
   `npm run dev`.
2. **The static mount is registered last.** FastAPI checks routes in
   registration order, so `app.mount("/", StaticFiles(...))` is the final line
   in `app.py` — otherwise it shadows `/corridor` and everything else. Tested
   directly, not assumed.

---

## Part 15 — Frontend

**React 19 + TypeScript + Vite.** Three views plus a slide-over panel:

| View | What it shows |
|---|---|
| **Overview** | corridor and plan at a glance; corridor asset availability stated beside the work that bought it |
| **Block Plan** | the SVG timeline — 52 section-line rows × the horizon, blocks coloured by department mix, **reliability labelled on every block**, traffic density shaded behind |
| **Corridor & Demand** | linear corridor strip, map inset, demand table, department filter |
| **Why panel** | for a block: the three closing chains against the hand-back envelope, the rule citation, reliability by block length. For a refused job: INFEASIBLE (with the lever table at 240/150/120 min) or OUTBID (with the price and what it would displace) |

No component library, no charting library, no map library. Five hand-drawn SVG
visualisations. A map library needs a tile server, which does not work offline.

Every number on screen is read from a backend response. Nothing is re-derived
in the frontend, and no value is defaulted — "no plan computed yet" and "zero
blocks" are different statements and render differently.

---

## Part 16 — PostgreSQL persistence (optional, default OFF)

27 tables, snapshot-versioned. The frozen dataset is snapshot 1: 16,189 rows
across 21 data tables, loaded from exactly the frozen CSVs.

- `dataset_snapshots` — one row per loaded dataset version.
- Data tables — the planning inputs, **every one carrying `row_no`**.
- `plans`, `plan_blocks`, `plan_deferred`, `approvals` — the one thing the
  frozen CSVs genuinely cannot hold, because plans previously died with the
  process.

**Row order is load-bearing.** `load_trains()` derives each Train id as
`f"{train_number}#{i}"` from the row's position in the file. An early version
read rows back in `ctid` order, displaced 1,730 of 2,978 rows, and *still
reproduced the plan by coincidence* — which is exactly why `row_no` is now on
every table and `blockplan_db/verify.py` proves the database rebuilds the
reference plan byte for byte.

Plan identity is the composite `(snapshot_id, plan_id)`, so two snapshots
cannot silently overwrite each other's plans while `plan_id` stays
`2db53586d84f` for the frozen data.

Enable with `BLOCKPLAN_DATA_SOURCE=postgres` and `BLOCKPLAN_PERSIST_PLANS=1`.
Neither is required to start.

---

## Part 17 — Running it

```bash
# once, with network
pip install -r backend/requirements.txt
cd frontend && npm install

# thereafter, no network at all
python run.py                 # builds frontend if needed, serves both on :8000
python run.py --no-warm       # skip the multi-minute scenario warmup
python run.py --port 8080
python run.py --rebuild       # force a frontend rebuild
```

`run.py` sets `BLOCKPLAN_WARM_ON_STARTUP=1`; plain `uvicorn` does not. Warmup
precomputes all eight scenarios' windows and default plans — right for "once
before the demo," wrong for a test suite.

The standalone core needs nothing but numpy and ortools:

```bash
cd Dataset/blockplan
python demo.py        # 12-job readable illustration
python dense.py       # the real evaluation instance
python ablation.py    # where does the reliability constraint start to bite?
```

### Measured timing on this machine

| Operation | Time |
|---|---|
| Re-plan at a **theta the server has not solved** | **~11.7 s** |
| Re-plan at an **already-solved theta** (cached) | **~0.01 s** |
| Cold start with full warmup | ~70 s – 2 min |
| OUTBID explanation (a real re-solve) | ~4 s |

The project memory document records ~4 s for a solve. That came from a faster
machine. CP-SAT reports `deterministic_time ≈ 2.04` against its budget of 60,
so the solver is nowhere near its limit — this machine is simply about three
times slower at CP-SAT. **Measure on the actual presentation laptop before
rehearsing to any of these.**

---

## Part 18 — Failure modes and what the system actually does

| Situation | Actual behaviour |
|---|---|
| A job cannot fit any permitted window | Deferred, and `POST /plan/{id}/explain/{job}` returns **INFEASIBLE** with the lever table at 240/150/120 min showing why each length fails |
| A job could fit but lost to cheaper work | Deferred as **OUTBID**, with the price of forcing it in and the specific job it would displace |
| Theta set so high nothing qualifies | Returns a plan with more deferrals, not an error (`test_infeasible_theta_returns_a_plan_not_an_error`) |
| Solver hits the deterministic budget | Returns the best feasible solution with its bound. On this instance it proves optimality well inside the budget |
| PostgreSQL absent | Irrelevant — CSV is the default and nothing requires the database |
| LightGBM / scikit-learn absent | Irrelevant — the catalogue duration source is the default |

---

## Part 19 — Answering a jury

**"Where is the AI?"** Four mechanisms, all squarely AI as the field defines
it: constraint optimisation (CP-SAT set packing over ~16,700 columns, solved to
proven optimality); combinatorial search (bounded enumeration over a
compatibility graph); reasoning under uncertainty (Monte Carlo chance
constraint over three stochastic closing chains); and supervised learning
(quantile regression on execution history — optional, and honestly reported as
not beating a lookup table on the split that matters).

**"Why CP-SAT and not RL or a genetic algorithm?"** Because the hard
constraints are safety rules, and a method that satisfies them "usually" is not
usable. CP-SAT proves optimality and proves feasibility. It also reproduces —
run it twice, get the same plan, which a railway safety audit will require and
a stochastic search cannot offer.

**"Is this real Indian Railways data?"** Partly, and the split is documented per
table in `manifest.json`. Infrastructure, stations and the passenger timetable
are real public data (DataMeet / IR, CC0). Maintenance jobs, block requests,
freight paths and execution outcomes are synthetic, generated from documented
distributions. This is a reproducible synthetic benchmark, not IR maintenance
data.

**"Are the TMS/SMMS/TDMS schemas official?"** **No.** They are
*project-owned ingestion contracts* — our own definition of what such a feed
would look like, used to prove the planner can consume a live feed instead of
CSVs. Do not describe them as official Indian Railways schemas.

**"Your cross-department share went from 18.8 % to 36.4 % — is that the
method?"** No, and thank you for asking. That figure is chosen by solver
tie-breaking, not determined by the model; it spans roughly 27–55 % across
equally optimal solutions. The results that *are* invariant are objective,
traffic cost, jobs done and reliability — which is where the argument lives.

**"What is the weakest part?"** Two candidates, both documented. The hand-back
chain structure is our synthesis of three separately-sourced procedures and
carries confidence 0.60 — no Indian Railways equivalent of a single
possession-in-charge was found. And κ and λ are the entire quantitative content
of "more departments means more risk"; they are declared assumptions, and the
conclusion should be checked against a sweep of them.

---

## Part 20 — Glossary

- **Absolute block signalling** — only one train may occupy a block section
  between two stations at a time.
- **Ballast** — crushed stone supporting the sleepers, distributing wheel loads
  and draining the track bed.
- **Block burst / overrun** — work fails to finish inside the sanctioned time;
  the delay falls on the trains queued behind it.
- **Column** — one bundle of jobs placed in one specific window. The CP-SAT
  decision variable.
- **CP-SAT** — OR-Tools' constraint solver, SAT-based with conflict-driven
  clause learning plus integer search.
- **Deferral penalty** — what it costs to leave a job undone across the
  horizon: `criticality × 100 / (1 + slack)`.
- **Hand-back** — returning the section to traffic. Complete only when the
  slowest department's closing chain finishes.
- **OHE / catenary** — the 25 kV overhead contact system.
- **Power block (P)** — OHE de-energised, isolated and earthed. Does *not* by
  itself stop trains.
- **Set packing** — choose a maximum-value collection of sets (columns) with no
  element (job, slot, resource) used twice.
- **Tamping** — packing ballast under sleepers to restore track geometry. The
  activity that compels OHE and S&T attendance.
- **Theta (θ)** — the minimum acceptable probability of on-time hand-back.
  0.90 here.
- **Traffic block (T)** — a bar on trains entering the section.

---

## Part 21 — Quick reference

```
CORRIDOR   JTJ -> ED, Southern Railway            182.0 km
           27 stations (4 junctions: TPT, MGSJ, SA, ED)
           52 section-lines (26 UP + 26 DN)
           108 real trains; 2,978 movements = 2,568 real + 410 SYNTH freight

DEMAND     175 requested jobs (ENGG 79 / SNT 49 / TRD 47)   SYNTH
           -> 238 jobs after 6 RULE pairings
           -> 449 bundles -> 11,648 windows -> 16,746 columns

POLICY     theta 0.90    kappa 0.15    lambda_close 6.0 min     all DECL
           block lengths 150 / 240 min (RULE)
           max span 8.0 km   max bundle size 5                  DECL

SOLVER     OR-Tools CP-SAT set packing
           num_workers 1, random_seed 1, deterministic budget 60

PLAN       plan_id 2db53586d84f   140 blocks   174 done   1 deferred
           objective 337.4   OPTIMAL   traffic 299.2   min R 0.90

QUOTE      objective, traffic cost, overrun, done/deferred, reliability
DO NOT     block count, cross-department share, utilisation (tie-break)
```

---

*Verified against the repository on 2026-09-08. If a figure here disagrees with
the repository, the repository wins and this document is wrong — say so rather
than resolving it silently.*
