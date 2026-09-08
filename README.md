# BlockPlan

**Automatic maintenance block planning for Indian Railways** — bundles work
that railway rules already couple into shared track possessions, and proves
each one hands the line back on time.

Smart India Hackathon 2026 · Problem Statement 26027 · Jolarpettai–Salem–Erode
corridor, Southern Railway.

`CP-SAT` · `Monte Carlo` · `FastAPI` · `React` · runs offline from one command

<!-- Add a screenshot: save one to docs/screenshot.png and uncomment the line below.
![BlockPlan block plan view](docs/screenshot.png)
-->

---

## The problem

Track, signalling and overhead-line staff all need the same stretch of line
closed. Today each department asks separately, so the line is withdrawn three
times over — and every withdrawal delays trains.

Much of that work is *already coupled by rule*. Tamping a track alters its
level, and ACTM Ch.17 requires due notice to overhead-line staff before any
alteration to alignment or level. A tamping job therefore already implies an
overhead-line job, whether or not anyone plans them together.

The catch is that a shared block is only useful if it ends on time — and now
three independent departments have to finish, so the block ends when the
**slowest** one does. That makes hand-back a probability, not a deadline.

## What it does

- **Bundles rule-coupled work** into one possession instead of three, using six
  pairing rules taken from Indian Railways manuals, each with its citation.
- **Guarantees reliability.** Every block is constrained to at least a 90 %
  modelled probability of handing back on time, simulated over three
  independent departmental closing chains.
- **Proves optimality.** CP-SAT set packing over ~16,700 candidate columns,
  solved to proven optimum, deterministically — the same input gives the same
  plan on every machine.
- **Explains every decision.** For a scheduled block: the three closing chains,
  the rule that forced the pairing, reliability at each permitted length. For a
  refused job: whether it was *infeasible* at every block length, or *outbid* —
  and if outbid, what forcing it in would cost and which job it would displace.
- **Answers capacity questions.** Eight what-if scenarios; the backlog scenario
  takes 340 jobs, defers 152, and says exactly which.

## Results

Six methods on an identical instance:

| Method | Blocks | Jobs done | Traffic cost ↓ | Weakest block reliability ↑ |
|---|---|---|---|---|
| B0 Dept-wise, no reliability | 161 | 161 | 391.4 | 0.74 |
| B1 Dept-wise + reliability | 160 | 160 | 430.8 | 0.90 |
| B2 Fixed-calendar | 105 | 175 | 743.4 | 0.73 |
| B3 Greedy-earliest | 161 | 161 | 1750.2 | 0.03 |
| B4 Bundle-only | 138 | 175 | 272.8 | 0.74 |
| **BlockPlan** | 140 | 174 | **299.2** | **0.90** |

Traffic cost is weighted train-minutes of delay. **The two columns have to be
read together:** B4 looks cheaper only because it admits blocks whose weakest
link hands back on time 74 % of the time, against a 90 % floor. It is not
planning better — it is accepting risk this method refuses.

Reference plan: **140 blocks, 174 of 175 jobs completed, objective 337.4,
proven optimal.** Reproducible from the checked-in data and one seed; the
figures above come from `Dataset/blockplan-dataset/dataset/scenarios/method_comparison.csv`.

## How it works

```
175 maintenance jobs
   |  6 rule-based pairings (IRTMM, ACTM — each cited)
   v
238 jobs  ->  449 compatible bundles  ->  11,648 candidate windows
   |  Monte Carlo over work durations + ENGG/SNT/TRD closing chains;
   |  discard any bundle below the reliability floor
   v
16,746 columns  ->  CP-SAT set packing  ->  140 blocks, proven optimal
```

Blocks are 150 or 240 minutes (the Railway Board norm), span at most 8 km, and
hold at most five jobs. Traffic cost is priced against the corridor's real
published timetable — 108 trains, 2,568 movements.

## Quick start

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

Serves the API and the UI from one process on <http://localhost:8000>. Add
`--no-warm` to skip the scenario warmup, `--port 8080` to move the port.

The analytical core also runs standalone, needing only numpy and ortools:

```bash
cd Dataset/blockplan && python dense.py
```

## Tech stack

| Layer | Choice |
|---|---|
| Optimiser | Google OR-Tools CP-SAT, deterministic mode |
| Uncertainty | Monte Carlo over log-normal durations + departmental closing chains |
| Backend | FastAPI + Pydantic, Python 3.14 |
| Frontend | React 19 + TypeScript + Vite; hand-drawn SVG, no chart or map library |
| Storage | Frozen CSVs by default; PostgreSQL optional |
| Tests | 405 backend (pytest), 163 frontend (vitest) |

## Project structure

```
Dataset/          the analytical core and the frozen dataset
  blockplan/        core.py — the solver, runnable standalone
  blockplan-dataset/
    config/         rules (manual-cited) and assumptions (declared)
    dataset/        planning inputs, 8 scenarios, frozen benchmarks
backend/          FastAPI service, planning + explanation
  blockplan_db/     PostgreSQL persistence      — optional
  blockplan_ml/     learned duration model      — optional
  blockplan_ingest/ TMS/SMMS/TDMS feed adapters — optional
frontend/         React UI: overview, block plan, corridor & demand
run.py            single entry point
```

All three optional subsystems are off by default; `python run.py` works without
any of them installed.

## Data and provenance

| Real public data | Synthetic, generated |
|---|---|
| Stations, sections, corridor geometry | Maintenance jobs and block requests |
| Passenger timetable (108 trains, 2,568 movements) | Freight paths, execution outcomes |

**This is a reproducible synthetic benchmark, not Indian Railways maintenance
data.** The infrastructure and timetable are real; maintenance demand and
execution outcomes are generated from documented distributions, because that
data is not public. Per-table provenance is in
`Dataset/blockplan-dataset/dataset/metadata/manifest.json`.

The TMS/SMMS/TDMS ingestion schemas are **project-owned contracts** written to
show the planner can consume a live feed — they are not official Indian
Railways schemas.

## Contributing

Parts of this repository are frozen, and the tests enforce it. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before making changes.

## Acknowledgements

Station, section and timetable data from the
[DataMeet railways dataset](https://github.com/datameet/railways) (CC0).
Operating rules cited from the Indian Railways Track Machines Manual, the AC
Traction Manual and the General Rules; each citation and its confidence is
recorded in `Dataset/blockplan-dataset/config/rules.yaml`.
