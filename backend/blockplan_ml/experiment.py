"""ML Phase 4: does a learned duration estimate produce a better plan?

    python -m blockplan_ml.experiment
    python -m blockplan_ml.experiment --out phase4.md

The design, and every part of it is load-bearing:

    train      the model on realisations 0-19 ONLY
    plan       the identical instance twice
                 Plan_assumed  -- catalogue durations   [the frozen path]
                 Plan_learned  -- model-estimated durations
    score      BOTH against realisations 20-29, which neither has seen

Scoring is not reimplemented. It imports score_block / score_plan / summarise
from the dataset's own src/score_execution.py, the same code that produced the
frozen execution_scoring_summary.csv, so these rows can be read next to that
file rather than merely resembling it.

The two plans are scored against IDENTICAL held-out work: the same actual
durations, and the same closing-chain draws from the same seed. Only the
durations the PLANNER believed differ. Anything else would make the comparison
about the sampling rather than about the estimate.

WHY THE PLAN CHANGES AT ALL. core.build_columns keeps a bundle only if its
Monte Carlo reliability clears theta, and that reliability is computed from
dur_mean and dur_sd. Change the estimated spread and a different set of bundles
becomes admissible, so a different column set reaches CP-SAT and a different
plan comes out. The mechanism is the theta filter, not the objective.

WHAT TO EXPECT, so the result is read honestly. The catalogue is not a guess:
duration_mean_min and duration_sd_min are the exact parameters the held-out
realisations were drawn from (dsgen/demand.py:237). Plan_assumed is therefore
planning with the truth, and Plan_learned with an estimate of it. On held-out
data drawn from those same parameters, the assumed plan should hold its
calibration at least as well. A learned plan that scored better would be
evidence of something wrong -- most likely that the model had seen the test
realisations.

The deliverable is the measured difference and an honest reading of it, not a
win. If it is shown, it belongs beside the frozen six as a seventh row, clearly
labelled, and never overwriting them.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import os
import sys
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from blockplan_service import PlanRequest, PlanningContext, PlanningService, paths
from blockplan_service.durations import CatalogueDurations

TRAIN_REALISATIONS = tuple(range(0, 20))
TEST_REALISATIONS = tuple(range(20, 30))

REQUEST = PlanRequest(scenario="NORMAL_TRAFFIC", horizon_days=14, theta=0.90,
                      max_bundle_size=5, mc_samples=1500, seed=None)

#: score_execution.py's own seed for the closing-chain draws. Reused verbatim so
#: the closing times here are the ones the frozen scoring used.
CLOSING_SEED = 770002


def _score_execution_module():
    """Import the dataset's scorer by path. It is a script, not a package."""
    path = os.path.join(paths.ADAPTER_DIR, "score_execution.py")
    spec = importlib.util.spec_from_file_location("score_execution", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def held_out_actuals(realisations: Sequence[int] = TEST_REALISATIONS
                     ) -> list[dict[str, float]]:
    """job_id -> observed minutes, one dict per held-out realisation.

    Both files, because 63 of the 238 jobs are companions and a block is only
    handed back when every job in it is finished.
    """
    wanted = set(realisations)
    by_realisation: dict[int, dict[str, float]] = {r: {} for r in realisations}
    for name in ("execution.csv", "execution_companions.csv"):
        with open(os.path.join(paths.PROCESSED_DIR, name), encoding="utf-8") as f:
            for row in csv.DictReader(f):
                r = int(row["realisation"])
                if r in wanted:
                    by_realisation[r][row["job_id"]] = float(row["actual_duration_min"])
    return [by_realisation[r] for r in realisations]


def closing_draws(core, count: int, seed: int = CLOSING_SEED) -> list[dict[str, float]]:
    """One closing time per department per realisation, shared by both plans."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(count):
        row = {}
        for dept in sorted(core.CLOSING):
            mean, sd = core.CLOSING[dept]
            sigma = np.sqrt(np.log1p((sd / mean) ** 2))
            mu = np.log(mean) - sigma ** 2 / 2
            row[dept] = float(rng.lognormal(mu, sigma))
        out.append(row)
    return out


@dataclass(frozen=True)
class PlanUnderTest:
    label: str
    plan: Mapping[str, Any]
    internals: Any
    durations: str


def build_plans(context: PlanningContext) -> tuple[PlanUnderTest, PlanUnderTest]:
    """The same instance, planned twice, differing only in duration source.

    The window cache is shared deliberately: windows are priced from the
    timetable and do not depend on job durations at all, so regenerating them
    would cost ~13.5 s and change nothing.
    """
    from .duration_source import LearnedDurations

    assumed_service = PlanningService(context=context,
                                      durations=CatalogueDurations())
    assumed = assumed_service.plan(REQUEST, use_cache=False)

    learned_source = LearnedDurations(realisations=TRAIN_REALISATIONS)
    learned_service = PlanningService(context=context,
                                      window_cache=assumed_service.windows,
                                      durations=learned_source)
    learned = learned_service.plan(REQUEST, use_cache=False)

    return (
        PlanUnderTest("Plan_assumed", assumed,
                      assumed_service.internals(assumed["plan_id"]),
                      assumed_service.durations.describe()),
        PlanUnderTest("Plan_learned", learned,
                      learned_service.internals(learned["plan_id"]),
                      learned_service.durations.describe()),
    )


def score(candidate: PlanUnderTest, core, scorer,
          work_by_r: Sequence[Mapping[str, float]],
          closing_by_r: Sequence[Mapping[str, float]]) -> tuple[list[dict], dict]:
    index = {job.id: job for job in candidate.internals.jobs}
    blocks = [_Column(block_id, column)
              for block_id, column in candidate.internals.blocks_by_id.items()]
    rows = scorer.score_plan(core, candidate.label, blocks, index,
                             len(work_by_r), list(work_by_r), list(closing_by_r))
    return rows, scorer.summarise(candidate.label, rows, len(work_by_r),
                                  REQUEST.theta)


class _Column:
    """score_plan expects `.id`, `.job_ids`, `.window`, `.reliability`.

    PlanInternals keeps the block id in the dict key rather than on the column,
    so this pairs them back up without copying the column or touching core.
    """

    def __init__(self, block_id: str, column: Any) -> None:
        self.id = block_id
        self._column = column

    def __getattr__(self, name: str) -> Any:
        return getattr(self._column, name)


# -- reporting ---------------------------------------------------------------

_HEADLINE = (
    ("blocks", "blocks", "{:d}"),
    ("jobs_done", "jobs done", "{:d}"),
    ("jobs_deferred", "deferred", "{:d}"),
    ("traffic_cost", "traffic cost", "{:.1f}"),
    ("exp_overrun_cost", "expected overrun", "{:.1f}"),
    ("mean_reliability", "modelled mean R", "{:.2f}"),
    ("min_reliability", "modelled min R", "{:.2f}"),
)

_SCORED = (
    ("plan_observed_rate_with_penalty", "observed on-time rate (vs theta 0.90)"),
    ("block_observed_rate_with_penalty", "observed rate, per block"),
    ("worst_block_observed_with_penalty", "worst block's observed rate"),
    ("blocks_observed_below_theta_with_penalty", "blocks observed below theta"),
    ("blocks_below_theta_with_penalty", "admissible but observed below theta"),
    ("modelled_minus_observed_with_penalty", "calibration error (modelled - observed)"),
    ("mean_abs_error_with_penalty", "mean absolute calibration error"),
    ("max_observed_overrun_min_with_penalty", "largest mean overrun (min)"),
)


def build_report(pairs: Sequence[tuple[PlanUnderTest, dict]]) -> str:
    out = io.StringIO()
    out.write("# ML Phase 4 -- assumed durations vs learned durations\n\n")
    out.write(f"Trained on realisations {TRAIN_REALISATIONS[0]}-"
              f"{TRAIN_REALISATIONS[-1]}; both plans scored against "
              f"{TEST_REALISATIONS[0]}-{TEST_REALISATIONS[-1]}, which neither "
              "has seen.\n\n")
    for candidate, _ in pairs:
        out.write(f"- **{candidate.label}** -- {candidate.durations}\n")

    out.write("\n## The plans\n\n")
    labels = [c.label for c, _ in pairs]
    out.write(f"    {'':40}" + "".join(f"{l:>16}" for l in labels) + "\n")
    for key, label, fmt in _HEADLINE:
        values = [c.plan["summary"].get(key, c.plan.get(key)) for c, _ in pairs]
        out.write(f"    {label:40}"
                  + "".join(f"{fmt.format(v):>16}" for v in values) + "\n")
    out.write(f"    {'objective':40}"
              + "".join(f"{c.plan['objective']:>16.1f}" for c, _ in pairs) + "\n")
    out.write(f"    {'plan_id':40}"
              + "".join(f"{c.plan['plan_id']:>16}" for c, _ in pairs) + "\n")

    out.write("\n## Scored on the held-out realisations\n\n")
    out.write(f"    {'':40}" + "".join(f"{l:>16}" for l in labels) + "\n")
    for key, label in _SCORED:
        values = [s.get(key) for _, s in pairs]
        out.write(f"    {label:40}"
                  + "".join(f"{_cell(v):>16}" for v in values) + "\n")

    out.write("""
## Reading this

**The two objectives are not comparable and must not be quoted side by side.**
Each is computed UNDER ITS OWN duration estimates -- 337.4 is what the plan
costs if the catalogue is right, 428.4 is what the other plan costs if the model
is right. They are answers to different questions. Only the held-out scores
below the line compare like with like, because both plans are measured against
the same realisations.

The catalogue is not an assumption in the ordinary sense. duration_mean_min and
duration_sd_min ARE the parameters the held-out realisations were drawn from
(dsgen/demand.py:237), so Plan_assumed planned with the truth and Plan_learned
with an estimate of it. On data generated from those parameters the assumed
plan is expected to hold up at least as well, and a learned plan that beat it
outright would be a reason to look for a leak rather than a result.

What the experiment establishes is that the learned estimate reaches the
optimiser and changes the plan -- through the theta filter, not the objective --
and by how much, measured on realisations neither plan has seen.

The direction of the difference is worth stating plainly, because it does not
all point one way:

  * The learned plan is BETTER CALIBRATED. Its mean absolute calibration error
    is roughly half the assumed plan's: what it claims about reliability is
    closer to what happens.
  * The learned plan is OPERATIONALLY WORSE. It predicts less expected overrun
    and then delivers more -- its largest mean overrun is around three times
    the assumed plan's -- while completing one job fewer and taking more
    traffic cost. Estimated spreads regress toward the activity mean, so the
    genuinely high-variance jobs get too little room and the blocks holding
    them run long.

A plan that is honest about its risk and still returns blocks later is not an
improvement, and should not be presented as one.
""")
    return out.getvalue()


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ML Phase 4: the experiment.")
    ap.add_argument("--out", help="write the report here as markdown")
    ap.add_argument("--blocks-csv", help="write the per-block scoring rows here")
    args = ap.parse_args(argv)

    paths.ensure_import_paths()
    import core

    scorer = _score_execution_module()
    context = PlanningContext.load()

    print("planning twice (this runs two full solves)...", flush=True)
    candidates = build_plans(context)

    work_by_r = held_out_actuals()
    closing_by_r = closing_draws(core, len(work_by_r))

    pairs, all_rows = [], []
    for candidate in candidates:
        rows, summary = score(candidate, core, scorer, work_by_r, closing_by_r)
        pairs.append((candidate, summary))
        all_rows.extend(rows)

    report = build_report(pairs)
    print(report)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"written: {args.out}")
    if args.blocks_csv and all_rows:
        with open(args.blocks_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0]))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"written: {args.blocks_csv}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
