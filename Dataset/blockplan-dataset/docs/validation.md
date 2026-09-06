# Validation

`python validate_dataset.py` runs 25 checks in five groups and exits non-zero on
any CRITICAL failure.

## Groups
- **Source** — a scaffold build fails by design, so placeholder geography can
  never be certified as real.
- **Network** — coordinates inside India; unique station codes; positive section
  lengths; the corridor sequence is contiguous; every consecutive pair has a
  section-line; every section is evidenced by at least one real train.
- **Timetable** — plausible dwell allowing for midnight crossing; contiguous
  stop sequences; plausible daily train count; headways in range.
- **Maintenance** — every job on a real section; footprint inside the section;
  department matches the activity catalogue; protection matches the catalogue;
  plausible duration triples; well-formed resources; jobs longer than the
  largest permitted block flagged as needing deferral rather than silently
  dropped.
- **Bundling and scenarios** — Class D jobs present; no self-contradictory job;
  pairing rules reference real activities and all carry citations; scenario
  multipliers sane.
- **Provenance** — every emitted column has a registered provenance row. The
  build fails if a new column is added without one.

## Two bugs the validator caught during development
Both were real, and both would have silently corrupted results:

1. **Midnight-crossing dwell.** Times are minutes-of-day, so a stop spanning
   midnight legitimately has departure < arrival. The naive check flagged it;
   the fix compares modulo the day and bounds the dwell instead.
2. **Derived headways of 65 minutes.** The 5th percentile of observed gaps was
   being used directly as the headway. But a headway is an infrastructure
   *capability*: sparse traffic is not evidence that a line cannot take trains
   closer together. Observation may only tighten the configured default, never
   loosen it.

## Known warnings that are not errors
- Jobs longer than the largest permitted block are expected. Deep screening at
  150 ± 30 minutes plus a compelled companion genuinely may not fit 240 minutes
  reliably. The correct behaviour is deferral with an explanation, which is what
  the optimiser does.
