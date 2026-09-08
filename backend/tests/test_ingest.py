"""TMS / SMMS / TDMS ingestion: the contract, the mapping, and the round trip.

The round trip is the test that matters. Export the frozen dataset into feed
format, ingest it back, plan, and require the reference plan. An adapter tested
only against data invented to suit it tests the invention; this one is fed the
dataset every published figure came from, so a mapping error moves the plan and
cannot hide.

Two did, while this was being written, and both are pinned below:

  * duration bounds derived as mean +/- 3 sigma instead of read from the
    catalogue -- 6 and 50.4 minutes against the catalogue's 18 and 65;
  * every job defaulted to resource instance 0, which core.py:287 reads as
    "these 110 jobs cannot be bundled with each other".

Nothing here needs a database. The feed is JSON on disk.
"""
from __future__ import annotations

import csv
import json
import os

import pytest

from blockplan_ingest import feeds, verify
from blockplan_ingest.contract import (
    DEPARTMENT_OF,
    SOURCE_SYSTEMS,
    ContractError,
    parse_demand,
    validate,
)
from blockplan_ingest.datasource import (
    FeedDataSource,
    FeedDataSourceError,
    from_env,
    materialise,
)
from blockplan_service import paths

WORK_ORDER = {
    "work_order_id": "TMS-0001",
    "source_system": "TMS",
    "activity_code": "THROUGH_TAMPING",
    "section_id": "JTJ-TPT-UP",
    "km_from": 1.0,
    "km_to": 4.0,
    "due_day": 3,
    "criticality": 1.4,
    "duration_mean_min": 65.0,
    "duration_sd_min": 12.0,
}


@pytest.fixture(scope="module")
def frozen_jobs() -> list[dict[str, str]]:
    with open(os.path.join(paths.PROCESSED_DIR, "jobs.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def feed_dir(tmp_path_factory, frozen_jobs) -> str:
    directory = str(tmp_path_factory.mktemp("feed"))
    feeds.write_feed_directory(feeds.demand_to_feed_records(frozen_jobs), directory)
    return directory


# -- the contract ------------------------------------------------------------

def test_the_three_systems_map_onto_the_three_departments():
    assert DEPARTMENT_OF == {"TMS": "ENGG", "SMMS": "SNT", "TDMS": "TRD"}
    assert set(SOURCE_SYSTEMS) == {"TMS", "SMMS", "TDMS"}


def test_a_well_formed_work_order_is_accepted():
    demand = parse_demand(WORK_ORDER)
    assert demand.work_order_id == "TMS-0001"
    assert demand.dept == "ENGG"
    assert demand.resource_id is None


def test_unknown_fields_are_carried_not_discarded():
    """An integrator's own identifiers must survive, or they cannot reconcile
    a plan against their system."""
    demand = parse_demand({**WORK_ORDER, "their_ref": "WO/2026/9912"})
    assert demand.extra == {"their_ref": "WO/2026/9912"}


@pytest.mark.parametrize("field", [
    "activity_code", "section_id", "due_day", "criticality",
    "duration_mean_min", "duration_sd_min",
])
def test_a_missing_required_field_is_refused_not_defaulted(field):
    """core.Job itself refuses a job without a duration, due day or
    criticality. A default here would produce a plausible-looking job that
    enters bundles, reliability draws and the objective unnoticed."""
    with pytest.raises(ContractError) as exc:
        parse_demand({**WORK_ORDER, field: ""})
    assert field in str(exc.value)


def test_an_unknown_source_system_is_refused():
    with pytest.raises(ContractError) as exc:
        parse_demand({**WORK_ORDER, "source_system": "SAP"})
    assert "SAP" in str(exc.value)


def test_a_zero_length_footprint_is_refused():
    """footprints_overlap compares half-open intervals; a zero-length one can
    never overlap anything, so the job would silently ignore every conflict."""
    with pytest.raises(ContractError):
        parse_demand({**WORK_ORDER, "km_to": WORK_ORDER["km_from"]})


def test_a_negative_or_zero_duration_is_refused():
    with pytest.raises(ContractError):
        parse_demand({**WORK_ORDER, "duration_mean_min": 0})
    with pytest.raises(ContractError):
        parse_demand({**WORK_ORDER, "duration_sd_min": -1})


def test_one_bad_record_does_not_discard_the_feed():
    result = validate([WORK_ORDER, {**WORK_ORDER, "work_order_id": "BAD",
                                    "duration_mean_min": ""}])
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1
    assert not result.ok


def test_a_duplicate_work_order_is_rejected_not_overwritten():
    """Two systems using the same id is exactly the collision that would
    otherwise look like a job mysteriously disappearing."""
    result = validate([WORK_ORDER, dict(WORK_ORDER)])
    assert len(result.accepted) == 1
    assert "duplicate" in result.rejected[0][1]


def test_work_for_an_unknown_section_is_refused():
    result = validate([WORK_ORDER], known_sections=["SOMEWHERE-ELSE-UP"])
    assert not result.accepted
    assert "not on this corridor" in result.rejected[0][1]


def test_work_for_an_uncatalogued_activity_is_refused():
    """Its protection regime is unknown, and guessing whether a job needs a
    power block is not a guess anyone should make."""
    result = validate([WORK_ORDER], known_activities=["SOMETHING_ELSE"])
    assert not result.accepted
    assert "catalogue" in result.rejected[0][1]


def test_missing_resource_allocation_is_reported_not_hidden():
    """The fallback shares one instance across the class, which core.py:287
    reads as maximum contention. Conservative, but an assumption."""
    result = validate([WORK_ORDER])
    assert result.without_resource_allocation == ("TMS-0001",)
    assert "no resource allocation" in result.summary()

    allocated = validate([{**WORK_ORDER, "resource_id": "TAMPER_3"}])
    assert allocated.without_resource_allocation == ()


# -- reading feeds -----------------------------------------------------------

def test_each_system_publishes_its_own_file(feed_dir):
    for system in SOURCE_SYSTEMS:
        assert os.path.isfile(os.path.join(feed_dir, feeds.FEED_FILES[system]))


def test_the_frozen_demand_splits_across_the_three_systems(feed_dir):
    read = {f.source_system: len(f.records) for f in feeds.read_all(feed_dir)}
    assert read == {"TMS": 79, "SMMS": 49, "TDMS": 47}
    assert sum(read.values()) == 175


def test_a_record_in_the_wrong_systems_file_is_caught(tmp_path):
    """A routing mistake, and it would otherwise plan SNT work as ENGG."""
    path = tmp_path / feeds.FEED_FILES["TMS"]
    path.write_text(json.dumps({"work_orders": [
        {**WORK_ORDER, "source_system": "SMMS"}]}), encoding="utf-8")
    with pytest.raises(feeds.FeedError) as exc:
        feeds.read_feed(str(tmp_path), "TMS")
    assert "SMMS" in str(exc.value)


def test_a_missing_system_can_be_tolerated_or_required(feed_dir, tmp_path):
    partial = tmp_path / "partial"
    partial.mkdir()
    for system in ("TMS", "TDMS"):
        (partial / feeds.FEED_FILES[system]).write_text(
            open(os.path.join(feed_dir, feeds.FEED_FILES[system]),
                 encoding="utf-8").read(), encoding="utf-8")

    with pytest.raises(feeds.FeedError):
        feeds.read_all(str(partial), required=True)
    tolerated = feeds.read_all(str(partial), required=False)
    assert {f.source_system for f in tolerated} == {"TMS", "TDMS"}


def test_malformed_json_is_named(tmp_path):
    (tmp_path / feeds.FEED_FILES["TMS"]).write_text("{not json", encoding="utf-8")
    with pytest.raises(feeds.FeedError) as exc:
        feeds.read_feed(str(tmp_path), "TMS")
    assert "not valid JSON" in str(exc.value)


# -- the mapping -------------------------------------------------------------

def test_protection_comes_from_the_catalogue_not_the_feed():
    """A feed says "tamp this stretch". Whether tamping needs a power block is
    a rule. A source system must not be able to change it by publishing a
    field."""
    rows = feeds.to_job_rows([parse_demand({**WORK_ORDER, "needs_P": 1})])
    with open(os.path.join(paths.PROCESSED_DIR, "activities.csv"),
              encoding="utf-8") as f:
        catalogue = {r["activity_id"]: r for r in csv.DictReader(f)}
    expected = catalogue["THROUGH_TAMPING"]

    assert rows[0]["needs_T"] == expected["needs_T"]
    assert rows[0]["needs_P"] == expected["needs_P"]
    assert rows[0]["needs_D"] == expected["needs_D"]


def test_duration_bounds_come_from_the_catalogue_not_from_mean_and_sd():
    """The regression that the round trip caught.

    They are the truncation bounds of the lognormal core.py samples, they are
    per-activity constants in config/activities.yaml, and deriving them as
    mean +/- 3 sigma gave 6 and 50.4 where the catalogue says 18 and 65 --
    a differently truncated distribution and therefore a different plan.
    """
    rows = feeds.to_job_rows([parse_demand(WORK_ORDER)])
    assert float(rows[0]["duration_min_min"]) == 35.0
    assert float(rows[0]["duration_max_min"]) == 150.0

    derived_low = WORK_ORDER["duration_mean_min"] - 3 * WORK_ORDER["duration_sd_min"]
    assert float(rows[0]["duration_min_min"]) != derived_low


def test_the_resource_allocation_is_carried_through():
    """core.py:287 refuses to bundle two jobs that share a resource. Defaulting
    every job to instance 0 made 110 of 175 mutually exclusive."""
    allocated = feeds.to_job_rows([parse_demand(
        {**WORK_ORDER, "resource_id": "TAMPER_3"})])
    assert allocated[0]["resources"] == "TAMPER_3"

    unallocated = feeds.to_job_rows([parse_demand(WORK_ORDER)])
    assert unallocated[0]["resources"].endswith("_0")


def test_job_rows_match_the_frozen_column_layout():
    """The materialised tree is read by the frozen adapter's DictReader, which
    would see different keys if a column were added, renamed or reordered."""
    rows = feeds.to_job_rows([parse_demand(WORK_ORDER)])
    assert list(rows[0]) == list(feeds.JOB_COLUMNS)

    with open(os.path.join(paths.PROCESSED_DIR, "jobs.csv"), encoding="utf-8") as f:
        assert next(csv.reader(f)) == list(feeds.JOB_COLUMNS)


def test_provenance_records_which_system_asked_for_the_work():
    rows = feeds.to_job_rows([parse_demand(WORK_ORDER)])
    assert rows[0]["provenance"].endswith(":TMS")
    assert rows[0]["provenance"].startswith("F:ingested")


def test_every_frozen_job_survives_the_round_trip_by_value(frozen_jobs, feed_dir):
    """Field by field, comparing parsed values rather than text.

    Only three differ, all of them display or provenance fields the optimiser
    never reads: location_desc (a formatted km label), provenance (which now
    records the feed), and one uncertainty_level that sits on the 0.28 band
    edge -- the same rounding boundary documented in the ML training table.
    """
    rebuilt = {r["job_id"]: r for r in feeds.to_job_rows(
        feeds.validate_feeds(feeds.read_all(feed_dir)).accepted)}
    assert set(rebuilt) == {r["job_id"] for r in frozen_jobs}

    differing: dict[str, int] = {}
    for original in frozen_jobs:
        new = rebuilt[original["job_id"]]
        for column in feeds.JOB_COLUMNS:
            if original[column] == new[column]:
                continue
            try:
                if float(original[column]) == float(new[column]):
                    continue          # same value, different text
            except ValueError:
                pass
            differing[column] = differing.get(column, 0) + 1

    assert set(differing) <= {"location_desc", "provenance", "uncertainty_level"}
    assert differing.get("provenance") == len(frozen_jobs)
    assert differing.get("uncertainty_level", 0) <= 1


# -- the data source ---------------------------------------------------------

def test_materialising_produces_a_complete_tree(feed_dir, tmp_path):
    tree, validation = materialise(feed_dir, str(tmp_path / "tree"))
    assert tree.missing() == []
    assert len(validation.accepted) == 175
    assert not validation.rejected


def test_the_feed_replaces_jobs_and_nothing_else(feed_dir, tmp_path):
    """Infrastructure and the working timetable are not maintenance demand. A
    feed that claimed to supply them would be inventing an interface."""
    tree, _ = materialise(feed_dir, str(tmp_path / "tree"))
    for name, frozen_path in (("movements.csv", paths.MOVEMENTS_CSV),
                              ("sections.csv", paths.SECTIONS_CSV),
                              ("stations.csv", paths.STATIONS_CSV),
                              ("pairing_rules.csv", paths.PAIRING_RULES_CSV)):
        built = os.path.join(tree.processed_dir, name)
        assert open(built, encoding="utf-8").read() == \
            open(frozen_path, encoding="utf-8").read(), name


def test_every_scenario_gets_the_same_live_demand(feed_dir, tmp_path):
    """A live feed has one real backlog. Scenarios stop being different demand
    and become different traffic -- which is the question a division asks."""
    tree, _ = materialise(feed_dir, str(tmp_path / "tree"))
    scenarios = [r["scenario"] for r in csv.DictReader(
        open(tree.scenarios_csv, encoding="utf-8"))]
    assert len(scenarios) == 8

    baseline = open(tree.scenario_jobs_csv(scenarios[0]), encoding="utf-8").read()
    for scenario in scenarios[1:]:
        assert open(tree.scenario_jobs_csv(scenario), encoding="utf-8").read() \
            == baseline


def test_a_feed_with_nothing_usable_is_refused(tmp_path):
    directory = tmp_path / "empty"
    directory.mkdir()
    for system in SOURCE_SYSTEMS:
        (directory / feeds.FEED_FILES[system]).write_text(
            json.dumps({"work_orders": []}), encoding="utf-8")
    with pytest.raises(FeedDataSourceError) as exc:
        materialise(str(directory), str(tmp_path / "tree"))
    assert "no usable work orders" in str(exc.value)


def test_the_source_will_not_guess_a_feed_directory():
    with pytest.raises(FeedDataSourceError) as exc:
        from_env({})
    assert "BLOCKPLAN_FEED_DIR" in str(exc.value)


def test_the_source_describes_what_it_read(feed_dir):
    source = FeedDataSource(feed_dir)
    try:
        source.open()
        described = source.describe()
        assert "TMS" in described and "175 work orders" in described
    finally:
        source.close()


def test_feed_is_reachable_through_the_data_source_seam(feed_dir):
    from blockplan_service.datasource import resolve

    source = resolve({"BLOCKPLAN_DATA_SOURCE": "feed",
                      "BLOCKPLAN_FEED_DIR": feed_dir})
    try:
        assert source.name == "feed"
        assert source.open().missing() == []
    finally:
        source.close()


def test_the_default_is_still_the_frozen_csvs():
    """The feed is opt-in. Nothing about adding it may move the default."""
    from blockplan_service.datasource import CsvDataSource, resolve

    assert isinstance(resolve({}), CsvDataSource)


# -- the gate ----------------------------------------------------------------

@pytest.mark.slow
def test_planning_from_a_feed_reproduces_the_reference_plan(feed_dir, tmp_path):
    """The claim the whole adapter rests on.

    The frozen dataset, expressed as TMS/SMMS/TDMS work orders, ingested back
    through the real adapter, produces plan 2db53586d84f with the identical
    140-block fingerprint. Not "a similar plan" -- the same one.
    """
    tree, validation = materialise(feed_dir, str(tmp_path / "tree"))
    assert not validation.rejected

    plan = verify.plan_from(tree.root)
    assert plan.plan_id == verify.REFERENCE_PLAN_ID
    assert plan.objective == 337.4
    assert plan.blocks == 140
    assert plan.fingerprint == verify.REFERENCE_FINGERPRINT
    assert plan.matches_reference
