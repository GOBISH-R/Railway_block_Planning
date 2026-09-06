# BlockPlan — reference implementation (SIH 2026, PS 26027)

Skeleton for the planning core described in the technical blueprint.
Not a product. It exists so nobody on the team starts from an empty file
and so the interfaces between the three of you are already fixed.

## Run it

    pip install numpy ortools
    python demo.py       # 12-job readable illustration, sparse timetable
    python dense.py      # 15 jobs, 118 trains/day — the real evaluation instance
    python ablation.py   # does the reliability constraint change anything?

## Files

    core.py     everything: model, rules, compatibility, bundles, traffic,
                reliability, columns, CP-SAT solver, explanation, baselines,
                evaluation. Section headers name the production module each
                block becomes.
    demo.py     the 12-job example. Sparse timetable ON PURPOSE — it shows the
                degenerate case where all baselines tie.
    dense.py    the instance the evaluation should actually use.
    ablation.py measures where the reliability constraint starts to bite.
    *.csv       the four input tables.

## Provenance tags in the code

    RULE   traced to an Indian Railways manual (see pairing_rules.csv sources)
    DECL   a modelling parameter we chose. Editable. NOT a fact.
    SYNTH  generated instance data. NOT Indian Railways data.

Every numeric constant is tagged at its definition. Keep it that way.

## Known gaps, deliberately left

  - post-block caution cost for S&T bundles: specified, not implemented (~10 lines)
  - churn penalty for plan stability: measured at 68% baseline, not yet penalised
  - detention surrogate: not needed at MVP scale (window pricing is 0.04s)
