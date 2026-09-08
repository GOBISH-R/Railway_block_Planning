# Contributing

Parts of this repository are frozen on purpose. Every published number came
from one specific file at one specific version, so changing it invalidates the
results rather than improving them. The tests enforce what follows — this file
explains *why*, which the tests cannot.

## What is frozen

**`Dataset/blockplan/core.py`** — byte for byte, 44,044 bytes, SHA-256 pinned
in `backend/blockplan_service/paths.py` and asserted by
`backend/tests/test_frozen_artifacts.py`. Every benchmark figure in the README
was produced by this exact file.

**Everything under `Dataset/`** — the guard fails on *any* uncommitted change
in that tree, deletions included. That is deliberately broader than the list of
files anyone would call "the dataset": it is cheaper to explain a false alarm
than to discover a silent edit months later.

**The reference plan is a gate, not an expectation.** If `plan_id`, block
count, jobs done, jobs deferred or objective move from
`2db53586d84f` / 140 / 174 / 1 / 337.4 — stop and find out why. Do not update
the expected values to match the new output.

Changing any of the above needs a deliberate decision and a reason, not a
convenient moment.

## Rules that are not obvious from the code

**Reuse the `blockplan_adapter` loaders verbatim.** `load_trains()` derives
each Train id as `f"{train_number}#{i}"` from the row's *position in the file*.
A reimplementation that parses the same columns but loses row order produces a
different plan while every headline figure still looks right. This is why the
PostgreSQL path materialises a snapshot back out to CSVs instead of streaming
rows into objects, and why every database table carries `row_no`.

**Never describe the maintenance jobs, block requests, freight paths or
execution realisations as real Indian Railways operational data.** They are
synthetic. Equally, do not describe the TMS/SMMS/TDMS ingestion schemas as
official Indian Railways schemas — they are this project's own contracts.

**Line endings are pinned by `.gitattributes` (`* -text`).** With
`core.autocrlf=true`, git would otherwise rewrite `core.py`'s 1,003 LF endings
on checkout, change its byte count to 45,047, and break every hash referring to
it — while `git status` still reported a clean tree. When editing files with a
script, match each file's existing endings; a whole-file conversion buries a
three-line change in a thousand-line diff.

## Which results are safe to cite

This instance is **degenerate**. Re-solving with the objective pinned at its
proven optimum returns OPTIMAL at anywhere from 118 to 153 blocks, with
cross-department share spanning roughly 27 %–55 %. Solving with eight workers
instead of one returns 142 blocks where deterministic mode returns 140 — same
columns, same objective.

| Invariant across the optimal face | Chosen by solver tie-breaking |
|---|---|
| Objective value | Block count |
| Traffic cost | Cross-department share |
| Expected overrun | Block utilisation |
| Jobs done / deferred | |
| Reliability figures | |

Anything in the right column is an arbitrary point in a range of equally
optimal answers, not a measured property of the method. Making block count
well-defined would need a lexicographic tie-break, which would change `core.py`
and every benchmark number.

One correction worth knowing: **B4's traffic cost is 272.8.** A figure of 259.8
appears in some earlier material and is superseded — it came from a run whose
RNG ordering differed from the one that produced the checked-in CSV.

## Running the tests

```bash
cd backend && python -m pytest -q
```

```bash
cd frontend && npm test
```

Expect 405 backend tests passing and 54 skipped (the live-database suites),
and 163 frontend tests. `npx tsc -b` and `npm run build` should both be clean.

**Run the backend suite alone.** `core.py` keeps module-level state and the
planning service holds a per-process lock, so two concurrent pytest runs
contend and produce failures — typically in the HTTP and planner tests — that
vanish when the tests are run in isolation. If something fails, re-run that
test on its own before believing it.

The full backend suite takes 13–20 minutes; most of that is real CP-SAT solves.

## Optional subsystems

PostgreSQL, the learned duration model and feed ingestion are all off by
default, and each has a README in its package. Anything that changes the
default path has to reproduce the reference plan exactly — that is the standing
acceptance test for all three.
