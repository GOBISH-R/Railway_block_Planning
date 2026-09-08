"""Run the three splits and report what they measure.

    python -m blockplan_ml.evaluate
    python -m blockplan_ml.evaluate --out report.md

Three splits, three different questions, and the third is expected to fail:

    realisation-holdout   future executions of jobs already seen
    job-holdout (Group)   a job never executed before   <- the honest one
    activity-holdout      a kind of work never seen     <- expected failure

Each is scored against two references: the per-activity mean (a lookup) and an
oracle that reads the label's own generating parameter. The oracle is not a
model and never sees a feature -- it marks the ceiling.
"""
from __future__ import annotations

import argparse
import io
import sys

import numpy as np

from . import duration_model as dm
from . import training_table as tt


def _fmt(value: float, places: int = 3) -> str:
    return f"{value:.{places}f}"


def _pit_histogram(values: np.ndarray, width: int = 30) -> list[str]:
    """Calibration, binned on the quantile ladder itself.

    Six predicted quantiles cut the line into seven intervals of UNEQUAL width
    (0-0.10, 0.10-0.25, ... 0.95-1.00), so a fixed ten-bin histogram leaves
    empty bins that look like a defect and are only a binning artefact. Each
    interval is shown against the share it should hold if the forecast is
    calibrated: its own width.

    Ratios near 1.00 mean calibrated. The first and last running high means
    over-confident -- outcomes falling in the tails more often than the model
    says they will, which is the direction that matters for a theta constraint.
    """
    edges = [0.0, *dm.QUANTILES, 1.0]
    lines = []
    peak = 0.0
    shares = []
    for lo, hi in zip(edges, edges[1:]):
        mid = (lo + hi) / 2.0
        count = int(np.sum(np.isclose(values, mid)))
        share = count / max(len(values), 1)
        shares.append((lo, hi, count, share, hi - lo))
        peak = max(peak, share)
    for lo, hi, count, share, expected in shares:
        bar = "#" * int(round(width * share / peak)) if peak else ""
        lines.append(f"    {lo:.2f}-{hi:.2f} |{bar:<{width}}| {count:5d}"
                     f"  {share:.3f} vs {expected:.2f} expected"
                     f"  ({share / expected:.2f}x)")
    return lines


def _render_split(result: dm.SplitResult, out: io.StringIO) -> None:
    out.write(f"\n## {result.split}\n\n")
    out.write(f"{result.question}\n\n")
    out.write(f"train {result.train_rows} rows, test {result.test_rows} rows\n\n")

    out.write(f"    {'predictor':34} {'R2':>8} {'MAE':>8}\n")
    for score in result.scores:
        out.write(f"    {score.predictor:34} {_fmt(score.r2):>8} "
                  f"{_fmt(score.mae, 2):>8}")
        out.write(f"   {score.note}\n" if score.note else "\n")

    quantile_scores = [s for s in result.scores if s.pinball]
    if quantile_scores:
        taus = sorted(quantile_scores[0].pinball)
        out.write(f"\n    pinball loss (lower is better)\n")
        out.write(f"    {'':34}" + "".join(f"{t:>8}" for t in taus) + "\n")
        for score in quantile_scores:
            out.write(f"    {score.predictor:34}"
                      + "".join(f"{score.pinball[t]:>8.2f}" for t in taus) + "\n")
        out.write(f"\n    coverage (should approach the nominal level)\n")
        out.write(f"    {'':34}" + "".join(f"{t:>8}" for t in taus) + "\n")
        for score in quantile_scores:
            out.write(f"    {score.predictor:34}"
                      + "".join(f"{score.coverage[t]:>8.3f}" for t in taus) + "\n")

    for name, values in result.pit_values.items():
        out.write(f"\n    PIT histogram -- {name}\n")
        out.writelines(line + "\n" for line in _pit_histogram(values))


def build_report(table: tt.TrainingTable) -> str:
    out = io.StringIO()
    out.write("# Learned duration model -- offline evaluation\n\n")
    out.write(f"{table.rows} rows, {table.frame['job_id'].nunique()} jobs, "
              f"{table.frame['realisation'].nunique()} realisations, "
              f"{len(table.feature_columns)} legal features.\n\n")
    out.write("Excluded as label leakage: "
              + ", ".join(f"`{c}`" for c in sorted(tt.FORBIDDEN)) + ".\n")

    out.write("""
## What this evaluation can and cannot show

From `dsgen/demand.py:152-154`, a job's duration parameters are drawn from the
activity catalogue and nothing else:

    mean = trunc_lognormal(catalogue_mean, catalogue_sd * 0.5, ...)
    sd   = catalogue_sd * uncertainty_scale * uniform(0.8, 1.25)

Section geometry, km span, protection regime, resource class, criticality and
due day never enter the duration path. Conditional on `activity`, the label is
therefore independent of every other legal feature, and

    E[actual | features] = E[actual | activity]

exactly. The per-activity mean is not a baseline to beat: over the legal
feature set it is the Bayes-optimal predictor. A learned model matching it has
recovered the catalogue, which is the correct result. A learned model beating
it by a visible margin would be fitting realisation noise.

This is a property of how the dataset was generated, not of the model or the
features. It is stated here so no reader has to infer it from the numbers.
""")

    out.write("\n---\n")
    _render_split(dm.realisation_holdout(table), out)

    folds = dm.job_holdout(table)
    out.write("\n---\n")
    for result in folds:
        _render_split(result, out)

    out.write("\n### job-holdout, averaged over folds\n\n")
    names = [s.predictor for s in folds[0].scores]
    out.write(f"    {'predictor':34} {'mean R2':>9} {'sd':>7} {'mean MAE':>9}\n")
    for i, name in enumerate(names):
        r2s = np.array([f.scores[i].r2 for f in folds])
        maes = np.array([f.scores[i].mae for f in folds])
        out.write(f"    {name:34} {r2s.mean():>9.3f} {r2s.std():>7.3f} "
                  f"{maes.mean():>9.2f}\n")

    out.write("\n---\n")
    _render_split(dm.activity_holdout(table), out)

    return out.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the duration model.")
    ap.add_argument("--out", help="write the report here as markdown")
    args = ap.parse_args(argv)

    table = tt.build()
    report = build_report(table)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nwritten: {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
