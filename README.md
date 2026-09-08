# BlockPlan

**AI-powered automatic block planning to maximise asset availability for train
operations on Indian Railways.**
Smart India Hackathon 2026 — Problem Statement 26027.
Corridor: Jolarpettai (JTJ) → Salem → Erode (ED), Southern Railway.

---

## What problem this solves

Track, signalling and overhead-line staff all need the same stretch of line
closed to traffic. Today each department asks for its own possession, so the
line is withdrawn three times over — and every withdrawal delays trains.

Some of that work is *already coupled by rule*. Tamping a track alters its
level, and ACTM Ch.17 requires due notice to overhead-line staff before any
alteration to alignment or level. A tamping job therefore already implies an
OHE job, whether or not anyone plans them together.

**BlockPlan bundles rule-coupled work into shared blocks, and constrains every
bundle to a minimum probability of handing the line back on time.** The hard
part is not the bundling — it is the guarantee. Three departments now have to
finish, and the block ends when the *slowest* one does.

---

## Data provenance — read this before quoting anything

| Real public data | Synthetic (generated, labelled) |
|---|---|
| Stations, sections, corridor geometry | Maintenance jobs (175) |
| Passenger timetable — 108 trains, 2,568 movements | Block requests (175) |
| Source: DataMeet / Indian Railways, CC0 | Freight paths (410 movements) |
| | Execution outcomes (30 realisations) |

**This is a reproducible synthetic benchmark, not Indian Railways maintenance
data.** The infrastructure and timetable are real; the maintenance demand and
the execution outcomes are generated from documented distributions. Never
present the synthetic half as operational railway data. Per-table provenance is
in `Dataset/blockplan-dataset/dataset/metadata/manifest.json`.

The **TMS / SMMS / TDMS ingestion schemas** in `backend/blockplan_ingest/` are
**project-owned contracts** — our own definition of what such a feed would look
like, written to prove the planner can consume a live feed instead of CSVs.
They are not official Indian Railways schemas and must not be described as
such.

---

## Running it

Two one-time installs, with network:

```bash
pip install -r backend/requirements.txt
```

```bash
cd frontend && npm install
```

Then, with no network at all:

```bash
python run.py
```

Builds the frontend if needed, warms all eight scenarios, and serves the API
and the UI from one FastAPI process on <http://localhost:8000>.

```bash
python run.py --no-warm
```

`--no-warm` skips the multi-minute warmup; `--port 8080` moves the port;
`--rebuild` forces a frontend rebuild.

Verified on Python 3.14.6 with `ortools==9.15.6755`. Dependencies are pinned to
versions actually observed working, not to whatever pip resolves today.

The standalone analytical core needs only numpy and ortools:

```bash
cd Dataset/blockplan && python dense.py
```

`demo.py` is a 12-job readable illustration, `dense.py` the real evaluation
instance, and `ablation.py` measures where the reliability constraint starts to
bite.

### Measured timing on the development machine

| Operation | Time |
|---|---|
| Re-plan at a θ the server has not solved | **~11.7 s** |
| Re-plan at an already-solved θ (cached) | **~0.01 s** |
| Cold start with full warmup | ~70 s – 2 min |

Measure on the presentation machine before rehearsing to any of these. CP-SAT
is the part that varies between machines, and the difference between twelve
seconds of silence and an instant response changes how a demo feels.

---

## Repository layout

```
Dataset/                    FROZEN — holds CODE as well as data. See below.
  blockplan/                the standalone analytical core
    core.py                 44,044 bytes, 12 numbered sections, SHA-256 pinned
    demo.py dense.py        runnable standalone instances
    ablation.py             does the reliability constraint change anything?
    pairing_rules.csv       READ by demo.py and dense.py
    jobs/sections/trains.csv  EXPORTS, not inputs — nothing reads them
  blockplan-dataset/
    config/*.yaml           rules (manual-cited) + assumptions (our choices)
    src/blockplan_adapter.py  the ten loaders, reused verbatim
    src/dsgen/              the generators that built the dataset
    dataset/processed/      the planning inputs
    dataset/scenarios/      8 scenario job sets + the frozen benchmarks
    dataset/metadata/       provenance, data dictionary, quality report

backend/
  blockplan_api/            FastAPI app; static mount registered LAST
  blockplan_service/        planning service, window cache, explanations
  blockplan_db/             PostgreSQL — optional, default OFF
  blockplan_ml/             LightGBM duration model — optional, default OFF
  blockplan_ingest/         TMS/SMMS/TDMS feed adapters — optional, default OFF
  tests/                    405 tests

frontend/                   React 19 + TypeScript + Vite, 163 tests
plan.json                   Phase-0 mock fixture; used only by a contract test
run.py                      the single entry point
```

### `Dataset/` cannot be deleted, and PostgreSQL does not replace it

1. **It contains the optimiser.** `paths.ensure_import_paths()` puts
   `Dataset/blockplan` and `Dataset/blockplan-dataset/src` on `sys.path`;
   `core.solve` resolves to `Dataset/blockplan/core.py`.
2. **PostgreSQL mode still goes through it.** `DatabaseDataSource` materialises
   a snapshot back out to a directory of CSVs and hands it to the same adapter
   loaders — because `load_trains()` derives each Train id from the row's
   position in the file, so reimplementing the parsing would silently change
   the plan.
3. **CSV is the default.** `BLOCKPLAN_DATA_SOURCE` unset resolves to `csv`.

The database is a copy of the dataset plus somewhere to persist plans. It is
not a substitute for the folder.

---

## How it works

```
175 requested jobs  (ENGG 79 · SNT 49 · TRD 47)          synthetic
        |  6 mandatory pairing rules, each manual-cited
        v
238 jobs  (63 rule-generated companions)
        |  compatibility graph, max bundle 5, max span 8.0 km
        v
449 bundles
        |  permitted block lengths 150 / 240 min; traffic priced from
        |  the real movement table
        v
11,648 candidate windows
        |  Monte Carlo over work durations + three departmental closing
        |  chains; keep only P(hand back on time) >= theta
        v
16,746 columns
        |  CP-SAT set packing — one boolean per column
        v
140 blocks, objective 337.4, proven OPTIMAL
```

**Hand-back is the maximum over three independent closing chains** (ENGG
12±4 min, SNT 20±7, TRD 15±5). There is no Indian Railways equivalent of a
single nominated person-in-charge of a possession: the Inspector of Way
superintends engineering work, a TRD representative must remain on site for
every permit-to-work, and the Station Master signs the reconnection memo. The
block ends when the slowest of them finishes. That is why hand-back is a
probability here and not a deadline.

Key parameters — θ = 0.90, κ = 0.15, λ_close = 6.0 min — are **declared
assumptions**, not railway figures, and live in `config/assumptions.yaml` so
the whole assumption surface is visible on one screen. κ and λ are the entire
quantitative content of "more departments means more risk"; sweep them.

### Determinism

`num_workers=1`, `random_seed=1`, and a machine-independent deterministic
budget. A wall-clock limit is not reproducible: with several workers racing,
the same instance returned 140 blocks once and 137 the next time. A benchmark
whose numbers move between runs cannot support any claim made from it.

---

## Results

The reference plan, gated by `backend/tests/test_reference_plan.py`:

| | |
|---|---|
| `plan_id` | `2db53586d84f` |
| Blocks | 140 |
| Jobs completed | 174 of 175 |
| Jobs deferred | 1 |
| Objective | 337.4 (proven OPTIMAL) |

Six methods on the identical NORMAL_TRAFFIC instance
(`dataset/scenarios/method_comparison.csv`):

| Method | Blocks | Done | Deferred | Traffic cost | Weakest block R |
|---|---|---|---|---|---|
| B0 Dept-wise, no reliability | 161 | 161 | 14 | 391.4 | 0.74 |
| B1 Dept-wise + reliability | 160 | 160 | 15 | 430.8 | 0.90 |
| B2 Fixed-calendar | 105 | 175 | 0 | 743.4 | 0.73 |
| B3 Greedy-earliest | 161 | 161 | 14 | 1750.2 | 0.03 |
| B4 Bundle-only | 138 | 175 | 0 | 272.8 | 0.74 |
| **OURS** | 140 | 174 | 1 | 299.2 | **0.90** |

**Read B4 and OURS together or not at all.** B4 is cheaper on traffic cost
because it admits blocks whose weakest link hands back on time only 74 % of the
time, against a 90 % floor. It is not planning better; it is accepting risk
this method refuses. And fewer blocks is not better either — B2 takes the
fewest of any baseline and causes 743.4 weighted delay-minutes doing it.

### What is safe to quote, and what is not

This instance is **highly degenerate**: re-solving with the objective pinned at
its proven optimum returns OPTIMAL at anywhere from **118 to 153 blocks**, with
cross-department share spanning roughly 27 %–55 %.

| Invariant — safe to quote | Solver tie-break — do **not** quote as a result |
|---|---|
| Objective, traffic cost, expected overrun | Block count |
| Jobs done / deferred | Cross-department share |
| Reliability figures | Block utilisation |

So "cross-department share rose to 36.4 %" is not a measured effect of the
method. The reliability and traffic-cost results, where the argument actually
lives, are invariant.

> B4's traffic cost is **272.8**. A figure of 259.8 appears in some earlier
> material; it is superseded — it came from a run whose RNG ordering differed
> from the one that produced the checked-in CSV. The CSV is authoritative.

---

## Optional subsystems, all default OFF

| Subsystem | Enable with | Notes |
|---|---|---|
| PostgreSQL | `BLOCKPLAN_DATA_SOURCE=postgres`, `BLOCKPLAN_PERSIST_PLANS=1` | 27 tables, snapshot-versioned. `blockplan_db/verify.py` proves the database rebuilds the reference plan byte for byte. |
| Learned durations | see `backend/blockplan_ml/README.md` | **The model does not beat a per-activity lookup under `GroupKFold(job_id)`.** Read that README before quoting anything from it. |
| Live feed ingestion | `BLOCKPLAN_DATA_SOURCE=feed` | Project-owned contracts, not official schemas. |

`python run.py` works with none of them installed.

---

## Tests

```bash
cd backend && python -m pytest -q
```

```bash
cd frontend && npm test
```

405 backend tests pass (54 skipped — the database suites, absent PostgreSQL);
163 frontend tests pass. `npx tsc -b` and `npm run build` should both be clean.

Run the backend suite **alone**. `core.py` uses module-level state and the
planning service holds a per-process lock, so two concurrent pytest runs
contend and produce failures that vanish in isolation.

---

## Before you edit anything

The repository enforces these in code, not just here —
`backend/tests/test_frozen_artifacts.py` and `test_reference_plan.py`.

- **`Dataset/blockplan/core.py` is frozen**, byte for byte, SHA-256 pinned.
  Every published number came from that exact file. Editing it invalidates all
  of them.
- **Nothing under `Dataset/` may be left dirty.** The guard fails on any
  uncommitted change anywhere in that tree, deletions included.
- **The frozen plan is a gate.** If `plan_id`, block count, jobs done/deferred
  or objective move from `2db53586d84f` / 140 / 174 / 1 / 337.4 — stop and
  investigate. Do not update the expected values to match.
- **Reuse the `blockplan_adapter` loaders verbatim.** `load_trains()` derives
  each Train id from the row's position in the file; a reimplementation that
  misses that changes the plan silently.
- **Never describe the maintenance jobs, block requests, freight paths or
  execution realisations as real Indian Railways operational data.**

`.gitattributes` sets `* -text` deliberately: `core.autocrlf` would otherwise
rewrite `core.py`'s LF endings on checkout, change its byte count, and
invalidate every hash referring to it.
