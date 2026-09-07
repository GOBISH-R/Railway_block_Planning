# BlockPlan backend

Planning and explanation services around the frozen analytical core.

## What is here

```
blockplan_service/
    paths.py      asset locations, DatasetTree, sys.path wiring, core.py's frozen hash
    datasource.py WHERE the planning inputs come from: frozen CSVs or PostgreSQL
    context.py    PlanningContext -- the tables read once, held immutably
    windows.py    WindowCache -- the ~13.5 s generate_windows step, cached per scenario
    planner.py    PlanningService -- THE PLANNING LOCK, plan cache, pipeline, DTO shaping
    explain.py    ExplanationService -- why a block exists, why a job was refused
blockplan_db/
    schema.sql    snapshot-versioned tables; see its ROW ORDER note before editing
    connection.py connection settings from the environment; never guesses a target
    loader.py     the frozen CSVs -> snapshot 1 (write side)
    repository.py a snapshot -> a DatasetTree (read side)
    verify.py     proves the database reproduces the reference plan
blockplan_api/
    app.py        FastAPI routes for all nine endpoints; serves frontend/dist/ if built
    schemas.py    Pydantic v2 request/response models
tests/            context / cache / lock / explain / API / packaging / frozen-artifact
                  / reference-plan / database tests
requirements.txt  pinned dependency versions
```

Run the API alone (dev, against a separately-running Vite dev server):

```
uvicorn blockplan_api.app:app --port 8000
```

Startup loads the frozen dataset once. The first plan per scenario pays window
generation (~20 s); after that the cache serves it.

**For the packaged app (API + built frontend, one port, no network), use
`python run.py` at the repo root instead** -- see the root `CLAUDE.md`'s
packaging section. `BLOCKPLAN_WARM_ON_STARTUP=1` (which `run.py` sets)
precomputes all eight scenarios before the server starts accepting requests;
plain `uvicorn` above does not set it, so scenario switching pays its full
cold cost on each new scenario's first request -- fine for backend
development, wrong for a demo.

Nothing here reimplements optimisation logic. The service orchestrates
`blockplan/core.py` (frozen, imported, never edited) and reuses the existing
`blockplan_adapter` loaders verbatim.

## Where the data comes from

The planner reads a **dataset tree**: a directory in the frozen layout. Two
sources can supply one, and everything downstream is unaware of which did.

```
BLOCKPLAN_DATA_SOURCE=csv        the frozen dataset          (DEFAULT)
BLOCKPLAN_DATA_SOURCE=postgres   snapshot 1 out of PostgreSQL
BLOCKPLAN_SNAPSHOT_ID=2          which snapshot (postgres only, default 1)
```

`GET /health` reports which is in use. **CSV is the default and nothing needs a
database**: `python run.py`, the demo and the whole test suite work on a machine
that has never installed PostgreSQL, and in CSV mode `psycopg` is never even
imported. The database path is opt-in until there is a reason for it not to be,
and today there is not — snapshot 1 *is* the frozen dataset. It starts earning
its keep when snapshots 2, 3, … hold live extracts.

The two are interchangeable, and that is measured rather than asserted. Both
produce plan `2db53586d84f`, objective 337.4, the same 140 blocks and the same
block fingerprint (`tests/test_datasource.py`, `tests/test_db_verify.py`,
`python -m blockplan_db.verify`).

The database source **materialises**: it writes the snapshot to a temporary
directory at startup and hands back that tree. That is deliberate — the
`blockplan_adapter` loaders take file paths and must be reused verbatim, and one
of them (`load_trains`) derives each train's id from its row's position in the
file, so a reimplementation that missed row order would silently change the
plan. See `blockplan_db/repository.py`.

Loading the database in the first place:

```
python -m blockplan_db.loader           # frozen CSVs -> snapshot 1
python -m blockplan_db.verify           # prove it rebuilds the reference plan
```

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
