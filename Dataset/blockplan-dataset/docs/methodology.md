# Generation methodology

## Principle
Real where public data exists; synthetic only where it does not; and every
synthetic value generated from a stated model rather than an arbitrary draw.

## 1. The corridor is discovered, not asserted
We name two real endpoint station codes and one via-anchor. The builder then:
1. finds every real train whose published stop list contains all three in order;
2. takes the fullest stopping pattern as the candidate station sequence — the
   slowest passenger train stops nearly everywhere;
3. keeps a station only if at least `min_supporting_trains` distinct real trains
   stop there, so a single anomalous route cannot inject a station.

The topology is therefore a consequence of published data. `sections.support_trains`
records how many real trains evidence each section, so a reader can see the
strength of the evidence for every edge.

## 2. Distances
Great-circle distance between consecutive real station coordinates, then scaled
by a single factor so the corridor total matches the published route distance
from `trains.json` where a train covers the corridor. A chord is always shorter
than the track it approximates, so a scale below 1.0 indicates the published
distance covers a different span and the scaling is rejected — the dataset then
records unscaled distances and flags them. `manifest.json` records the factor.

## 3. Maintenance demand is Poisson from periodicity
Not `random.randint`. For each activity and each section-line:

    expected jobs in the horizon = assets x horizon_days / periodicity_days
    realised count               ~ Poisson(expected)

Two consequences worth stating to a judge:
- the **mix** of activities is an output of the periodicity table and the asset
  inventory, not a weighting we chose. Turnout work is common because there are
  many turnouts on a short cycle; deep screening is rare because its cycle runs
  to years.
- arrivals in a Poisson window are uniform, so **due dates are uniform by
  construction**, not by assumption. An overdue tail is added in proportion to
  the backlog multiplier.

The METHOD is defensible. The NUMBERS — periodicities, asset counts, durations —
are assumptions and live in `config/`. Both statements must be made together.

### Calibration is visible
`OHE_INSPECTION` periodicity was raised from 90 to 240 days and its footprint
lengthened, because an inspection outing covers a long stretch at a time and the
original value made TRD dominate the mix. That change is recorded in a comment
in `activities.yaml`. It is a calibration of the activity mix, not of any
railway fact, and it is visible rather than buried.

## 4. Protection comes from the catalogue, never from the job
A job copies `needs_T/P/D` from its activity. Two jobs of the same activity can
therefore never disagree about what protection they need, and a validator check
enforces it.

## 5. Class D jobs are generated on purpose
Work that requires the *negation* of a block — a track-circuit shunting check
that needs trains running, an OHE measurement that needs the line energised — is
generated deliberately. A dataset without these lets a broken compatibility
engine look correct.

## 6. Freight is generated and labelled
Public timetables carry almost no freight, and CAG Report 45/2018 records goods
trains running "without any scheduled timing" at all. Freight is therefore
generated from an hourly weight profile and every row carries `is_synthetic=1`.
This is the largest synthetic component of the traffic layer.

## 7. Planning data and evaluation data are separated
The planner sees `duration_mean_min` and `duration_sd_min`. It never sees
`execution.csv`, which holds N independent realisations of what actually
happened. Hand-back success is scored against those realisations. Keeping the
files separate is what makes the reliability claim testable rather than circular.

## 8. Scenarios vary the week, never the railway
Every scenario uses the identical infrastructure and the identical real
timetable. Only demand, freight volume, duration uncertainty and urgency change.
We never invent a different railway.

## 9. Scenario demand is generated, never cloned
Higher-demand scenarios do not duplicate existing jobs. A duplicate keeps its
original's section, km footprint and exclusive resource id, so it can never be
bundled with — or even run concurrently with — the job it was copied from. That
is not extra demand, it is unschedulable demand, and it distorted exactly the two
scenarios meant to show the method under load.

`src/generate_scenario_jobs.py` builds each scenario's demand through the same
`dsgen.demand.generate_jobs` the base dataset uses, with that scenario's declared
`demand_scale`, `backlog`, `uncertainty_scale` and `urgency_shift`. Extra demand
therefore arrives as genuinely new jobs with their own locations, footprints,
durations, resources and due dates.

Every scenario uses the base dataset's seed, so a scenario that changes only
traffic or urgency reproduces the base job set exactly and is a controlled
variation on the same maintenance programme. `scenario -> seed -> parameters ->
realised job count` is written to `dataset/scenarios/scenario_jobs_manifest.csv`.
Control check: `jobs_NORMAL_TRAFFIC.csv` is byte-identical to `processed/jobs.csv`.

## 10. Service class comes from the operator's own train name
Published Indian Railways train names abbreviate — "SF Exp", "SF Special",
"Expres", "InterCity". Matching only the fully spelled words left 24 trains and
576 movements unclassified, riding on a fallback weight. Classification now reads
those abbreviations as tokens, in a fixed order, which is reading the source
string rather than guessing at it. There is no fallback to a train-numbering
heuristic: a name that cannot be read stays UNKNOWN, the UNKNOWN share is a
validation check, and the fallback weight is declared in assumptions.yaml.
Current UNKNOWN share: 0 of 2978 movements.

## 11. Track attributes are declared, and labelled as declared
`track_source` is `declared` for all 52 section-lines: tracks and electrification
come from `config/corridor.yaml`, not from OpenStreetMap corroboration. This is
an acceptable prototype position and it is asserted by the `track_source_labelled`
validation check so it cannot quietly stop being true. OSM integration is
available in `dsgen/sources.py` and is not a prerequisite.
