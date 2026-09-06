# BlockPlan backend

Planning and explanation services around the frozen analytical core.

## What is here

```
blockplan_service/
    paths.py      frozen-asset locations, sys.path wiring, core.py's frozen hash
    context.py    PlanningContext -- frozen CSVs read once, held immutably
    windows.py    WindowCache -- the ~13.5 s generate_windows step, cached per scenario
    planner.py    PlanningService -- THE PLANNING LOCK, plan cache, pipeline, DTO shaping
    explain.py    ExplanationService -- why a block exists, why a job was refused
blockplan_api/
    app.py        FastAPI routes: /plan, /plan/{id}, block + explain endpoints
    schemas.py    Pydantic v2 request/response models
tests/            context / cache / lock / explain / API / frozen-artifact tests
requirements.txt  pinned dependency versions
```

Run the API:

```
uvicorn blockplan_api.app:app --port 8000
```

Startup loads the frozen dataset once. The first plan per scenario pays window
generation (~20 s); after that the cache serves it.

Nothing here reimplements optimisation logic. The service orchestrates
`blockplan/core.py` (frozen, imported, never edited) and reuses the existing
`blockplan_adapter` loaders verbatim.

## Setup

```
pip install -r requirements.txt
```

Verified on Python 3.14.6 with numpy 2.5.2, ortools 9.15.6755, PyYAML 6.0.3.

## Use

```python
from blockplan_service import PlanningService, PlanRequest

service = PlanningService()                       # loads the frozen CSVs once
plan = service.plan(PlanRequest(
    scenario="NORMAL_TRAFFIC",
    horizon_days=14,
    theta=0.90,
    max_bundle_size=5,
    mc_samples=1500,
))
```

`service.windows.warm(service.context, 14)` precomputes all eight scenario
window sets (~2–3 minutes) so no request pays the cold cost. Phase 8 will call
this at startup.

## Tests

```
python -m pytest
```

The suite runs real plans and takes several minutes. It is slow on purpose:
mocking the optimiser would test nothing worth testing.

## Three things worth knowing

**The lock is the point.** `core.py` holds mutable module-level state
(`THETA`, `KAPPA`, `TRAIN_WEIGHT`, … and one shared `RNG`) and is configured by
monkey-patching those globals. That is fine for a script and unsafe behind a
threadpool. `planner.py` holds a single module-level lock covering reset →
configure → override → pipeline → shape. Refactoring `core.py` to thread
parameters through signatures was considered and explicitly rejected: it would
break the freeze and invalidate the verified benchmark numbers.

**The window cache is what makes synchronous HTTP viable.** `generate_windows`
is the single most expensive stage and depends only on
`(sections, trains, horizon, keep_per_day)` — never on jobs, theta, bundle size
or mc_samples. Only the scenario moves it. Eight window sets exist in the whole
system. Without the cache every request pays that cost again and the tool looks
like it has hung rather than like it is slow.

**A gotcha waiting for Phase 2.** `core.explain_refusal()` declares
`theta: float = THETA`, and that default is bound at import time — so
monkey-patching `core.THETA` per request does *not* change it. The `/explain`
endpoint must pass `theta=` explicitly or it will silently explain refusals
against 0.90 no matter what the request asked for. `build_columns` has the same
signature pattern; `planner.py` already passes `theta=` explicitly for that
reason.

**Block count and cross-department share are not determined by the model.**
See CLAUDE.md. The optimal face of this instance contains solutions from 118 to
153 blocks at the identical optimal objective. Traffic cost, objective and
reliability are invariant across that face; block count and cross-department
share are chosen by solver tie-breaking. The tests assert the former exactly
and deliberately do not pin the latter.
