"""Provenance registry.

Every field the dataset emits is registered here with a class:

    A  real public data, used as published
    B  derived from real public data by a documented computation
    C  derived from an official Indian Railways rule or manual
    D  synthetic, generated from a documented distribution
    E  explicit modelling assumption

Nothing is written to the dataset without a row here. `assert_complete()`
fails the build if a column appears in an output file with no registration,
which is what stops provenance drifting out of date as the code changes.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Field:
    table: str
    field: str
    classification: str          # A | B | C | D | E
    source: str
    source_url: str
    derivation_method: str = ""
    generation_method: str = ""
    assumption: str = ""
    validation_method: str = ""
    confidence: float = 1.0


DATAMEET = "https://github.com/datameet/railways"
OSM = "https://www.openstreetmap.org"
IRTMM = "https://indianrailways.gov.in/railwayboard/uploads/codesmanual/IRTMM-RDSO/"
ACTM = "https://indianrailways.gov.in/railwayboard/uploads/codesmanual/ACTraction-II-P-I/ACTractionIIPartICh6.htm"
GR = "https://irfca.org/docs/rulebook/gr-pway.html"
CAG = ("https://cag.gov.in/uploads/download_audit_report/2018/"
       "Chapter_3_Utilisation_of_resources_and_infrastructure_for_track_"
       "maintenance_of_Report_No.45_of_2018_%E2%80%93_Compli_1.pdf")

REGISTRY: list[Field] = [
    # ---------------------------------------------------------- stations.csv
    Field("stations", "station_code", "A", "DataMeet Indian Railways stations.json (CC0)", DATAMEET,
          validation_method="non-empty, unique, matches source"),
    Field("stations", "station_name", "A", "DataMeet stations.json property `name`", DATAMEET,
          validation_method="non-empty"),
    Field("stations", "latitude", "A", "DataMeet stations.json Point geometry", DATAMEET,
          validation_method="6 < lat < 38 (India bounds)"),
    Field("stations", "longitude", "A", "DataMeet stations.json Point geometry", DATAMEET,
          validation_method="68 < lon < 98 (India bounds)"),
    Field("stations", "zone", "A", "DataMeet stations.json property `zone`", DATAMEET),
    Field("stations", "state", "A", "DataMeet stations.json property `state`", DATAMEET),
    Field("stations", "is_junction", "B", "Derived from corridor topology", DATAMEET,
          derivation_method="degree > 2 in the corridor graph, or name contains 'Junction'"),
    Field("stations", "seq", "B", "Position along the corridor", DATAMEET,
          derivation_method="order of appearance in the supported station sequence"),

    # ---------------------------------------------------------- sections.csv
    Field("sections", "section_id", "B", "Derived", DATAMEET,
          derivation_method="'{from_code}-{to_code}-{line}'"),
    Field("sections", "from_station_code", "A", "DataMeet schedules.json", DATAMEET),
    Field("sections", "to_station_code", "A", "DataMeet schedules.json", DATAMEET),
    Field("sections", "line", "B", "Track configuration", OSM,
          derivation_method="UP/DN for a double line, SINGLE for a single line"),
    Field("sections", "length_km", "B", "Derived from real station coordinates", DATAMEET,
          derivation_method="haversine between consecutive station coordinates, then "
                            "scaled so the corridor total matches the published route "
                            "distance from trains.json where available",
          validation_method="> 0; corridor total within 15% of published distance"),
    Field("sections", "tracks", "A/E", "OpenStreetMap `tracks` where mapped, else config fallback", OSM,
          assumption="where OSM has no `tracks` tag the configured fallback is used and the row is flagged"),
    Field("sections", "electrified", "A/E", "OpenStreetMap `electrified=contact_line`, else config", OSM,
          assumption="Salem division is publicly stated to be entirely electrified on broad gauge"),
    Field("sections", "headway_min", "B/E", "Derived from the real timetable", DATAMEET,
          derivation_method="5th percentile of observed gaps between consecutive real "
                            "trains on the section-line; falls back to the configured "
                            "default when too few movements are observed",
          confidence=0.6),
    Field("sections", "degraded_factor", "E", "Modelling assumption", "",
          assumption="headway multiplier when one line of a double line is blocked"),
    Field("sections", "support_trains", "B", "Evidence count", DATAMEET,
          derivation_method="number of distinct real trains traversing this station pair"),

    # ------------------------------------------------------------ trains.csv
    Field("trains", "train_number", "A", "DataMeet schedules.json `train_number`", DATAMEET,
          validation_method="matches a real train in the source"),
    Field("trains", "train_name", "A", "DataMeet schedules.json `train_name`", DATAMEET),
    Field("trains", "train_class", "B", "Classified from the real train name", DATAMEET,
          derivation_method="keyword match on the published train name and trains.json `type`",
          confidence=0.75),
    Field("trains", "is_synthetic", "D", "Freight generator flag", "",
          generation_method="true only for generated freight paths; false for every real train"),

    # ------------------------------------------------------- train_stops.csv
    Field("train_stops", "arrival_min", "A", "DataMeet schedules.json `arrival`", DATAMEET,
          validation_method="parses as HH:MM:SS; arrival <= departure at a stop"),
    Field("train_stops", "departure_min", "A", "DataMeet schedules.json `departure`", DATAMEET),
    Field("train_stops", "day", "A", "DataMeet schedules.json `day`", DATAMEET),
    Field("train_stops", "stop_seq", "B", "Order within the train's real stop list", DATAMEET),

    # ------------------------------------------------------ movements.csv
    Field("movements", "section_id", "B", "Real train mapped onto a derived section", DATAMEET,
          derivation_method="consecutive real stops define the section traversed"),
    Field("movements", "enter_min", "A/B", "Real departure time from the first station", DATAMEET),
    Field("movements", "direction", "B", "Derived", DATAMEET,
          derivation_method="ascending or descending corridor sequence"),

    # ------------------------------------------------------- activities.csv
    Field("activities", "protection_T/P/D", "C", "Indian Railways manuals", ACTM,
          derivation_method="per-activity protection regime; see config/activities.yaml "
                            "for the source on each row", confidence=0.88),
    Field("activities", "min_block_min", "C/E", "IRTMM where published, else assumption", IRTMM,
          assumption="only DEEP_SCREENING has a published minimum (four hours, IRTMM Ch.3); "
                     "all others are assumptions", confidence=0.88),
    Field("activities", "duration_mean/sd", "E", "Modelling assumption", "",
          assumption="no per-activity working times were found in public sources"),
    Field("activities", "periodicity_days", "E", "Modelling assumption", "",
          assumption="no public per-activity periodicity table was obtainable"),

    # ------------------------------------------------------------- jobs.csv
    Field("jobs", "job_id", "D", "Generated", "", generation_method="sequential, seed-stable"),
    Field("jobs", "dept", "C", "Department that owns the activity", IRTMM,
          derivation_method="from the activity catalogue; never set independently of it",
          validation_method="must equal activities.dept for the job's activity"),
    Field("jobs", "activity", "D", "Sampled from the activity catalogue", "",
          generation_method="Poisson arrivals with rate = assets x horizon / periodicity"),
    Field("jobs", "section_id", "D", "Placed on a REAL section", DATAMEET,
          generation_method="uniform over asset instances of the right type; the section "
                            "itself is real, the placement is synthetic"),
    Field("jobs", "location_desc", "B", "Human-readable location", DATAMEET,
          derivation_method="real station codes plus the synthetic km offset"),
    Field("jobs", "km_from/km_to", "D", "Generated within a real section", "",
          generation_method="uniform start, footprint length from the activity catalogue",
          validation_method="0 <= km_from < km_to <= section length"),
    Field("jobs", "needs_T/needs_P/needs_D", "C", "Protection regime from the catalogue", ACTM,
          derivation_method="copied from activities.csv so two jobs of the same activity "
                            "can never disagree", confidence=0.88,
          validation_method="must equal the catalogue row"),
    Field("jobs", "needs_train_movements/needs_live_ohe", "C",
          "Class D negations from the catalogue", ACTM,
          derivation_method="work that requires the opposite of a block", confidence=0.90),
    Field("jobs", "duration_mean_min/duration_sd_min", "D/E",
          "Sampled around the catalogue values", "",
          generation_method="per-job jitter around the activity mean; the catalogue value "
                            "itself is an assumption"),
    Field("jobs", "duration_min_min/duration_max_min", "E", "Catalogue bounds", "",
          assumption="plausible working-time bounds per activity"),
    Field("jobs", "min_block_min", "C/E", "Catalogue minimum block", IRTMM,
          assumption="only DEEP_SCREENING has a published minimum (four hours)"),
    Field("jobs", "due_day", "D", "Steady-state maintenance phase", "",
          generation_method="Poisson arrivals are uniform in the window, so due dates are "
                            "uniform by construction; an overdue tail is added in "
                            "proportion to the backlog multiplier"),
    Field("jobs", "criticality", "D/E", "Activity base times a defect draw", "",
          assumption="the activity base criticality is an assumption"),
    Field("jobs", "priority", "B", "Banded from criticality and due date", "",
          derivation_method="URGENT if overdue or criticality >= 2.0; HIGH if >= 1.4"),
    Field("jobs", "uncertainty_level", "B", "Banded from the coefficient of variation", "",
          derivation_method="HIGH if sd/mean > 0.28, LOW if < 0.15"),
    Field("jobs", "resources", "C/E", "Resource class from the catalogue, fleet size assumed", "",
          assumption="fleet counts per division are an assumption"),
    Field("jobs", "provenance", "D", "Self-describing tag", "",
          generation_method="records the generation model used for the row"),

    # --------------------------------------------------- pairing_rules.csv
    Field("pairing_rules", "compelled_dept", "C", "Indian Railways manuals", IRTMM,
          derivation_method="see config/rules.yaml; every row carries its own source and "
                            "confidence", confidence=0.82),

    # -------------------------------------------------- block_requests.csv
    Field("block_requests", "*", "D", "Synthesised from maintenance demand", "",
          generation_method="one request per job, with a preferred window drawn from the "
                            "department's declared preference; we do NOT have BDMS data "
                            "and do not claim to"),

    # ------------------------------------------------------- execution.csv
    Field("execution", "actual_duration_min", "D", "Stochastic realisation", "",
          generation_method="lognormal draw per job per realisation, used ONLY for "
                            "evaluation and never visible to the planner"),

    # ------------------------------------------------------- activities.csv
    Field("activities", "activity_id/label/asset/resource_class", "C/E",
          "Activity catalogue", IRTMM,
          derivation_method="activity taxonomy follows the departmental split in the "
                            "manuals; the asset class and resource class are ours"),
    Field("activities", "dept", "C", "Department owning the activity", IRTMM,
          derivation_method="P-Way / S&T / TRD split as used in the manuals"),
    Field("activities", "needs_T/needs_P/needs_D", "C", "Protection regime", ACTM,
          derivation_method="per-activity; see protection_source on each row",
          confidence=0.88),
    Field("activities", "needs_train_movements/needs_live_ohe", "C",
          "Class D negation flags", ACTM, confidence=0.90),
    Field("activities", "duration_mean_min/duration_sd_min", "E",
          "Modelling assumption", "",
          assumption="no per-activity working times were found in public sources"),
    Field("activities", "criticality_base", "E", "Modelling assumption", "",
          assumption="relative consequence of deferring this activity"),
    Field("activities", "min_block_provenance", "C/E", "Self-describing tag", IRTMM,
          derivation_method="C where a published minimum exists, E otherwise"),
    Field("activities", "protection_source", "C", "Citation carried in the row", ACTM),

    # ---------------------------------------------------- pairing_rules.csv
    Field("pairing_rules", "activity/companion_activity", "C",
          "Mandatory association from the manuals", IRTMM, confidence=0.82),
    Field("pairing_rules", "duration_mean_min/duration_sd_min", "E",
          "Modelling assumption", "",
          assumption="the companion task's working time"),
    Field("pairing_rules", "must_follow_parent/precedes_parent", "C",
          "Sequencing implied by the rule", IRTMM,
          derivation_method="e.g. OHE re-adjustment must follow track lifting; "
                            "cable clearance must precede deep screening"),
    Field("pairing_rules", "source/confidence", "C", "Citation and our confidence in it", IRTMM),

    # ------------------------------------------------------- other tables
    Field("sections", "is_single/track_source", "B",
          "Derived from the track configuration", OSM,
          derivation_method="is_single = tracks < 2; track_source records whether "
                            "the row came from OSM or from the declared fallback"),
    Field("trains", "direction", "B", "Derived from the real stop order", DATAMEET),
    Field("train_stops", "train_number/train_name/station_code", "A",
          "DataMeet schedules.json", DATAMEET),
    Field("movements", "train_number/train_class/from_code/to_code", "A/B",
          "Real train mapped onto a derived section", DATAMEET),
    Field("movements", "is_synthetic", "D", "Generated-freight flag", "",
          generation_method="true only for generated freight paths"),
    Field("execution", "realisation/job_id", "D", "Realisation index and key", "",
          generation_method="one row per job per stochastic realisation"),
    Field("resources", "resource_class/fleet_size/provenance", "E",
          "Modelling assumption", "",
          assumption="fleet counts available to the division over the horizon"),
    Field("scenarios", "*", "E", "Scenario multipliers", "",
          assumption="scenario definitions are ours; the infrastructure and the real "
                     "timetable are identical across every scenario"),

    # ------------------------------------------------------- assumptions
    Field("config", "kappa/lambda_close", "E", "Modelling assumption", "",
          assumption="the entire quantitative content of 'more departments means more risk'"),
    Field("config", "train_weight", "E", "Modelling assumption", "",
          assumption="relative train priority weights; not railway policy"),
    Field("config", "block_envelope", "C", "Corridor block norm", CAG,
          derivation_method="single 240-min block or two of 150 min", confidence=0.90),
]


def write(path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(REGISTRY[0]).keys()))
        w.writeheader()
        for r in REGISTRY:
            w.writerow(asdict(r))


def assert_complete(table: str, columns) -> list[str]:
    """Return columns of `table` that have no provenance row."""
    known = {r.field for r in REGISTRY if r.table == table}
    if "*" in known:
        return []
    missing = []
    for c in columns:
        if c in known:
            continue
        if any("/" in k and c in k.split("/") for k in known):
            continue
        missing.append(c)
    return missing
