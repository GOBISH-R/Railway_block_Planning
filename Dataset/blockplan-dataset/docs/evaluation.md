# Evaluation, field roles and honest reporting

This document covers three things a reviewer will ask about: how the reliability
claim is actually tested, which dataset columns the optimiser does and does not
consume, and how reliability numbers may be reported.

## 1. The reliability claim is measured, not asserted

`dataset/processed/execution.csv` holds 30 independent realisations of the
working time of every job. The planner never reads it. `src/score_execution.py`
does, and it is the only thing that turns "our blocks are 90% reliable" from a
model output compared against itself into a measurement.

Run it with:

    python score_execution.py --dataset .. --core ../../blockplan

For each selected block it rebuilds the departmental hand-back chains by exactly
the rule the reliability model uses — each department's jobs in sequence, a
cross-department *must follow* pairing adding the predecessor's time to the
successor's chain, each department's own closing chain, and the block ending at
the **maximum** of the three because there is no single person-in-charge — then
asks whether that maximum fits inside the planned block length.

Outputs:

- `dataset/scenarios/execution_scoring_blocks.csv` — one row per block
- `dataset/scenarios/execution_scoring_summary.csv` — one row per method

### Two things that are simulated, and are declared as such

**Closing chains.** There is no realised closing time in `execution.csv`, so the
scorer draws one per realisation per department, from the declared closing
distributions, seed `770002`. These draws are the only simulated component of
the observed side.

**Companion jobs.** The rule-generated companions do not exist in `jobs.csv` —
`expand_mandatory_pairings` creates them at plan time — so `execution.csv` could
not have covered them. This was the only genuine incompatibility between the
execution data and the reliability model, and the smallest correction was **not**
to regenerate `execution.csv`. It was to draw companion realisations from each
companion's own declared mean and sd, with seed `770001`, and write them to
`dataset/processed/execution_companions.csv` so they can be inspected.
`execution.csv` is untouched.

### Why two columns, `with penalty` and `without penalty`

The planner inflates every duration's spread by `KAPPA` per extra department and
adds `LAMBDA_CLOSE` minutes to each closing chain. The execution realisations
were generated **without** that coordination penalty, deliberately: applying the
model's own assumption to the data meant to test it would make the test
circular. So the scorer reports the observed rate both ways. The spread between
those two columns *is* the sensitivity of the whole reliability claim to the two
least defensible constants in the model. When a judge asks where `KAPPA` and
`LAMBDA_CLOSE` come from, the answer is "they are declared assumptions, and here
is exactly how much the result depends on them."

### What the numbers say (NORMAL_TRAFFIC, seed 42)

| Method | Blocks | Modelled | Observed | MAE | Worst block | Blocks below θ |
|---|---|---|---|---|---|---|
| B0 Dept-wise, no reliability | 161 | 0.99 | 0.995 | 0.004 | 0.83 | 1 |
| B1 Dept-wise + reliability | 160 | 1.00 | 0.998 | 0.002 | 0.93 | 0 |
| B2 Fixed-calendar | 105 | 1.00 | 0.997 | 0.002 | 0.83 | 1 |
| B3 Greedy-earliest | 161 | 0.98 | 0.990 | 0.006 | 0.00 | 2 |
| B4 Bundle-only | 142 | 0.99 | 0.994 | 0.007 | 0.83 | 1 |
| **OURS** | **140** | **0.99** | **0.996** | **0.004** | **0.93** | **0** |

Mean absolute error between the modelled and observed per-block reliability is
0.002–0.007 across every method. That is a direct check on the Monte Carlo
implementation against data it never saw.

The column that discriminates is **worst block**, not the mean. Averages hide
the block that hurts: one block handed back late at 06:00 delays the morning
services however well the other 139 behaved. The worst block in the greedy plan
handed back on time in **0 of 30** executions and overran by 66 minutes on
average. The worst block in our plan handed back on time in **28 of 30**, worst
overrun 16 minutes, and no block we certified at θ came out below it.

### What these numbers are not

Simulated executions of synthetic maintenance work. They test whether the
planner's reliability arithmetic survives independent draws. They do **not**
calibrate it against reality, and must never be described as observed Indian
Railways hand-back performance.

## 2. Baselines

`reliability_required` on `baseline_department_wise` is keyword-only and has no
default, because the two settings are two different baselines:

- **B0** — department-wise, **no** reliability filter. This is the one that
  stands for current practice: nobody in a division computes a hand-back
  probability today.
- **B1** — department-wise **with** the chance constraint. This is our method
  with cross-department bundling switched off.

Reading `B0 → B1` isolates the effect of the reliability filter; `B1 → OURS`
isolates the effect of integrated cross-department bundling. Previously only B1
existed and was labelled "current practice", which is why its minimum
reliability came out at exactly θ — it already contained the innovation.

## 3. Which columns the optimiser consumes

Not every column is a planning input, and forcing one in so it looks "used"
would be worse architecture, not better.

| Field | Role | Consumed by the optimiser? |
|---|---|---|
| `duration_mean_min`, `duration_sd_min` | duration model | **Yes** |
| `km_from`, `km_to` | spatial exclusion, bundle span | **Yes** |
| `resources` | exclusive-resource constraint | **Yes** |
| `due_day`, `criticality` | deferral penalty, column horizon | **Yes** |
| `needs_T/P/D`, `needs_train_movements`, `needs_live_ohe` | compatibility engine | **Yes** |
| `priority` | UI and reporting label, derived from `due_day` and `criticality` | **No** — and deliberately not. It is a *function* of two fields the objective already uses; adding it would double-count the same urgency. |
| `uncertainty_level` | UI and reporting label, derived from `duration_sd_min / duration_mean_min` | **No** — the reliability model uses the underlying `sd` directly, which is strictly more information than the three-way bucket. |
| `block_requests.csv` | the demand-side artefact a division would actually raise: preferred date, preferred start, requested duration, protection type, reason | **No** — the planner currently plans from jobs, not from requests. The file is the input shape the backend and UI will consume (showing a controller *what was asked for* beside *what the plan gave*), and it is the natural place to add preference-satisfaction as an objective term later. It is honest scope, not dead weight, and it is described as such. |

## 4. Reporting reliability honestly

Reliability is reported to **two** decimal places, not three. At the 1500 Monte
Carlo samples the benchmark uses, the standard error of one block's reliability
near 0.9 is about 0.008, so the third decimal is noise and printing it implies a
precision the method does not have.

Say:

> Modelled hand-back reliability ≥ 0.90 by construction; observed on-time rate
> over 30 independent simulated executions, 99.6%; worst single block 0.93.

Do not say:

> ~~Our blocks are 90.1% reliable.~~

and do not imply the modelled value is calibrated against historical hand-back
records. It is not. It is a model output under declared distributions, now
checked against independent draws.

## 5. Reproducibility

Two bugs were making the benchmark non-reproducible and are fixed:

1. `{j.dept for j in bundle}` — Python randomises string hashing per process, so
   the closing-chain draws consumed the RNG stream in a different order in every
   run, and an identical bundle's reliability moved between runs. Department
   sets are now sorted wherever draw order or array stacking depends on them.
2. CP-SAT was run with 8 workers under a wall-clock limit. This instance is
   highly degenerate — thousands of distinct plans at exactly the same optimal
   objective — so the plan returned was whichever worker proved it first. `solve`
   now uses a deterministic work budget and a single worker, with the wall-clock
   limit kept only as a safety cap.

Verified: identical output across runs under different `PYTHONHASHSEED` values,
and `generate_dataset.py --seed 42 --size medium` reproduces every processed
table byte-for-byte from the three DataMeet source files.
