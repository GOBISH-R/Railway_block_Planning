# blockplan_ml — learned duration estimation

Everything here is **off by default** and sits behind one gate: with the flags
unset, the planner must still produce plan `2db53586d84f`, 140 blocks,
objective 337.4. `tests/test_reference_plan.py` and
`tests/test_duration_source.py` both assert it.

`core.py` is not touched. The learned path writes two numbers onto each
`core.Job` — `dur_mean` and `dur_sd` — which is exactly what the catalogue
loader already writes. The frozen sampler, solver and objective run unchanged.

```
BLOCKPLAN_DURATION_SOURCE=catalogue            frozen dataset figures (DEFAULT)
BLOCKPLAN_DURATION_SOURCE=learned              model estimates
BLOCKPLAN_DURATION_TRAIN_REALISATIONS=0-19     which executions to fit on
```

LightGBM and scikit-learn are **not** imported unless `learned` is asked for,
so the packaged app still starts on a machine that has neither. (pandas is not
part of that promise — OR-Tools imports it regardless.)

```
pip install lightgbm scikit-learn scipy      # only needed for the learned path
python -m blockplan_ml.training_table        # build and describe the table
python -m blockplan_ml.evaluate --out r.md   # the three splits
python -m blockplan_ml.experiment --out p.md # Phase 4: assumed vs learned
```

## What the modules are

| file | what it does |
|---|---|
| `training_table.py` | the join, and **the leakage guard** |
| `duration_model.py` | LightGBM quantile models, the activity-mean baseline, an oracle |
| `duration_source.py` | the plug-in the planner consumes, moment-matched onto core's lognormal |
| `evaluate.py` | three splits, three questions |
| `experiment.py` | plan twice, score both on unseen realisations |

## Leakage, and the two that do not announce themselves

The label is `trunc_lognormal(duration_mean_min, duration_sd_min,
duration_min_min, duration_max_min)` (`dsgen/demand.py:237`), so those four are
excluded, and `uncertainty_level` with them because it is banded off `sd/mean`.

Two more are excluded that a reasonable person would have joined in:

```python
"minimum_duration_min":   max(60, int(j.duration_mean_min))
req = ceil((j.duration_mean_min + 1.0 * j.duration_sd_min) / 30) * 30
"requested_duration_min": max(j.min_block_min, req)
```

Both live in `block_requests.csv` and look like ordinary operational fields.
`minimum_duration_min` **is** `duration_mean_min`. The guard is an assertion
over the assembled frame, matched on the bare name after any join prefix, and
`tests/test_training_table.py` recomputes both formulas from the shipped CSVs
rather than trusting the reading of the generator.

## The ceiling, stated up front

From `dsgen/demand.py:152-154` a job's parameters are drawn from the activity
catalogue and nothing else:

```python
mean = trunc_lognormal(catalogue_mean, catalogue_sd * 0.5, ...)
sd   = catalogue_sd * uncertainty_scale * uniform(0.8, 1.25)
```

Section geometry, km span, protection regime, resource class, criticality and
due day never enter the duration path. **Conditional on `activity`, the label
is independent of every other legal feature.** The per-activity mean is
therefore close to the best any model can do here — not a baseline to beat.

Measured, mean R² over 5 folds:

| split | question | oracle | activity mean | LightGBM |
|---|---|---|---|---|
| realisation-holdout | future runs of **known** jobs | 0.718 | 0.741 | **0.762** |
| **job-holdout (Group×5)** | **an unseen job** | 0.633 | **0.551** | 0.484 |
| activity-holdout | unseen work type | 0.611 | −0.500 | **0.360** |

The model wins only where it can memorise a job it has already done. On the
operationally honest split it loses to a lookup. Removing six identifier
columns took that split from 0.294 to 0.484; the remaining gap is structural.

Its intervals are also over-confident: on job-holdout, outcomes land in the
outer tails about twice as often as the model claims. That matters directly for
a θ constraint, which is a probability statement.

## Phase 4, and how to read it

Both plans are scored against realisations 20–29 that neither has seen, using
the dataset's own `src/score_execution.py`.

- The learned plan is **better calibrated** — mean absolute calibration error
  0.003 against 0.007.
- The learned plan is **operationally worse** — one job fewer, more traffic
  cost, and a largest mean overrun of 19.7 minutes against 6.3.

**The two objectives are not comparable.** 337.4 and 428.4 are each computed
under their own duration estimates; only the held-out scores compare like with
like.

The catalogue is not a guess: `duration_mean_min` and `duration_sd_min` **are**
the parameters the held-out realisations were drawn from. Plan_assumed planned
with the truth. A learned plan that beat it outright would be a reason to look
for a leak, not a result.

If any of this is ever presented beside the benchmark it goes in as a
**seventh row**, labelled, never overwriting the frozen six. (There is no
longer a comparison screen in the app; the benchmark is presented from the
written evidence.)
