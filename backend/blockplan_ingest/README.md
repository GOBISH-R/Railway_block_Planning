# blockplan_ingest — TMS / SMMS / TDMS ingestion

Maintenance demand from the three source systems the problem statement names,
which map cleanly onto the three departments this project already plans for:

| system | | department | assets |
|---|---|---|---|
| **TMS** | Track Management System | ENGG | TRACK_KM, TURNOUT |
| **SMMS** | Signal Maintenance Management System | SNT | SIGNAL_POINT, TURNOUT |
| **TDMS** | Traction Distribution Management System | TRD | OHE_KM, TRACK_KM |

```
BLOCKPLAN_DATA_SOURCE=feed
BLOCKPLAN_FEED_DIR=<directory of three JSON files>    # or
BLOCKPLAN_FEED_URL=<base URL of three endpoints>      # exactly one of the two
```

Off by default — the frozen CSVs remain the default data source, and nothing
here is imported unless a feed is asked for.

## This is not a real schema, and says so

`contract.py` defines **the contract this system accepts**, not a reproduction
of any real interface. We do not have the TMS, SMMS or TDMS specifications, and
inventing field names then labelling them "the TMS schema" would be the same
fabrication CLAUDE.md rule 5 forbids for the synthetic maintenance data.

Every field is traced to the `core.Job` attribute it feeds. Connecting a real
system means writing a mapping onto this contract — and `REQUIRED_TO_PLAN` says
exactly which fields cannot be defaulted, because `core.Job` itself refuses a
job with no duration, due day or criticality.

Asked *"is that the real TMS schema?"* the answer is **no**. Asked *"what would
connecting the real one take?"* the answer is this file plus a field mapping.

## The round-trip gate

```
python -m blockplan_ingest.verify
```

Exports the frozen dataset **into** feed format, ingests it back through the
real adapter, plans, and requires plan `2db53586d84f` with the identical
140-block fingerprint. An adapter tested only against data invented to suit it
tests the invention; this one is fed the dataset every published figure came
from, so a mapping error moves the plan and cannot hide.

**It caught two while this was being written:**

- **Duration bounds.** Derived as mean ± 3σ, giving 6 and 50.4 minutes where
  the catalogue says 18 and 65. They are the truncation bounds of the lognormal
  `core.py` samples for reliability, they live in `config/activities.yaml`, and
  wrong bounds mean a different plan.
- **Resource allocation.** Every job defaulted to instance `_0`, which
  `core.py:287` reads as *"these 110 of 175 jobs cannot be bundled with each
  other"*.

## What a feed replaces

**Jobs, and nothing else.** Sections, stations, movements and pairing rules come
from the frozen tree unchanged — infrastructure, the working timetable and
departmental rules are not maintenance demand. A maintenance system raises work;
it does not publish the WTT or the ACTM.

Protection regimes come from the **catalogue**, never the feed: a feed says
"tamp this stretch"; whether tamping needs a power block is a rule, and a source
system must not be able to change it by publishing a field.

`resource_id` is optional, and **omitting it is not neutral** — the fallback
shares one instance across the class, which the planner reads as maximum fleet
contention. That is the conservative direction (more blocks, never fewer), but
it is an assumption, so `validate()` counts how many records relied on it.

## Scenarios change meaning under a live feed

The frozen dataset generates different demand per scenario. A live feed has
**one real backlog**, so its jobs become the job set for every scenario and what
varies is the *traffic* — freight weighting, extra passenger paths, withdrawn
windows. The question changes from "what if demand were higher" to "how does
today's actual backlog plan under peak traffic".

## Mock endpoints (demonstration only)

```
python -m blockplan_ingest.mock_systems --port 8100
  GET /tms/work-orders   /smms/work-orders   /tdms/work-orders   /health
```

Not imported by the backend, not started by `run.py`, not a dependency of
anything — the packaged app must keep working with **no network at all**. It
serves this project's own contract over HTTP so a demonstration can show data
arriving over the wire rather than read from disk. `/health` states plainly that
it is not a real system and does not emulate one.

Verified end to end: work orders pulled from those three endpoints, ingested,
planned → `2db53586d84f`, objective 337.4, 140 blocks, fingerprint matching.
