"""The training table: the join is right, and the leakage rule is enforced.

Two independent things are under test and only one of them is about ML.

The join must be exact -- 7,140 rows, every execution row matched to a job,
companions reconstructed the way core.py constructs them. A silently wrong join
produces a table that trains fine and means nothing.

The leakage guard must be an assertion that actually fires. A guard that has
never been observed to reject anything is a comment. So these tests do reject
things: they put each forbidden column back and require the build to fail.

No database, no model, no network. Building the table is a pure function of
the frozen CSVs.
"""
from __future__ import annotations

import pandas as pd
import pytest

from blockplan_ml import training_table as tt

EXPECTED_ROWS = 7140
EXPECTED_BASE_JOBS = 175
EXPECTED_COMPANIONS = 63
EXPECTED_REALISATIONS = 30


@pytest.fixture(scope="module")
def table() -> tt.TrainingTable:
    return tt.build()


# -- the join ---------------------------------------------------------------

def test_every_execution_row_is_present_exactly_once(table):
    """5,250 base + 1,890 companion. Both files, nothing dropped, nothing
    duplicated by a fan-out join."""
    assert table.rows == EXPECTED_ROWS
    assert len(table.frame.drop_duplicates(["realisation", "job_id"])) == EXPECTED_ROWS


def test_the_job_population_matches_the_pipeline(table):
    """238 is the number the planner reports as jobs_after_pairing, and it is
    pinned by test_reference_plan.py. The two must agree or one of them is
    describing a different instance."""
    counts = table.frame.groupby("is_companion")["job_id"].nunique().to_dict()
    assert counts == {0: EXPECTED_BASE_JOBS, 1: EXPECTED_COMPANIONS}
    assert table.frame["job_id"].nunique() == 238


def test_every_job_appears_in_every_realisation(table):
    per_job = table.frame.groupby("job_id")["realisation"].nunique()
    assert set(per_job.unique()) == {EXPECTED_REALISATIONS}
    assert sorted(table.frame["realisation"].unique()) == list(range(30))


def test_nothing_failed_to_join(table):
    """A left join that misses turns into NaN features, not an error."""
    for column in ("activity", "dept", "section_id", "km_from", "km_to",
                   "section_length_km", "section_support_trains"):
        assert table.frame[column].notna().all(), f"{column} has unmatched rows"


def test_base_jobs_join_to_everything(table):
    """The 175 catalogued jobs must match every reference table. Only
    companions are allowed gaps, and only the ones named below."""
    base = table.frame[table.frame["is_companion"] == 0]
    for column in ("activity_asset", "activity_periodicity_days",
                   "resource_fleet_size", "request_preferred_date",
                   "min_block_min", "priority"):
        assert base[column].notna().all(), f"{column} has unmatched base rows"


def test_four_companion_activities_have_no_catalogue_entry(table):
    """A property of the data, not a broken join.

    SNT_ASSOCIATION, POINT_MOTOR_RESET, TRACTION_BOND_JUMPER and
    CABLE_ROD_CLEARANCE are named only by pairing_rules.csv. They are compelled
    work, so they have no periodicity, asset class or catalogue duration of
    their own, and their activity_* features are legitimately NaN.

    Asserted explicitly so the NaNs are a stated fact rather than something a
    modeller discovers and quietly imputes.
    """
    missing = tt.activities_without_a_catalogue_entry()
    assert missing == ("CABLE_ROD_CLEARANCE", "POINT_MOTOR_RESET",
                       "SNT_ASSOCIATION", "TRACTION_BOND_JUMPER")

    companions = table.frame[table.frame["is_companion"] == 1]
    uncatalogued = companions[companions["activity"].isin(missing)]
    assert uncatalogued["activity_asset"].isna().all()
    assert companions[~companions["activity"].isin(missing)][
        "activity_asset"].notna().all()


def test_companions_carry_the_rule_that_compelled_them(table):
    """For the uncatalogued four this is the only activity-level information
    that exists, so it must be present for every companion."""
    companions = table.frame[table.frame["is_companion"] == 1]
    assert companions["compelled_by_rule_source"].notna().all()
    assert companions["compelled_by_rule_confidence"].notna().all()
    base = table.frame[table.frame["is_companion"] == 0]
    assert base["compelled_by_rule_source"].isna().all()


def test_the_label_is_present_and_positive(table):
    labels = table.labels()
    assert labels.notna().all()
    assert (labels > 0).all()


# -- companions, reconstructed as core.py builds them -----------------------

def test_companion_ids_resolve_to_their_parent_and_rule(table):
    """core.py names them f"{parent}c{k}" and k indexes the rules for the
    parent's activity, in CSV order (core.py:239-240, 208)."""
    companions = table.frame[table.frame["is_companion"] == 1]
    assert len(companions) == EXPECTED_COMPANIONS * EXPECTED_REALISATIONS

    parents = set(table.frame.loc[table.frame["is_companion"] == 0, "job_id"])
    assert set(companions["parent_job_id"]) <= parents

    rules = tt.companion_catalogue(pd.read_csv(tt.paths.PAIRING_RULES_CSV))
    by_parent = table.frame[table.frame["is_companion"] == 0].drop_duplicates(
        "job_id").set_index("job_id")
    for row in companions.drop_duplicates("job_id").to_dict("records"):
        k = int(str(row["job_id"]).rpartition("c")[2])
        expected = rules[by_parent.loc[row["parent_job_id"], "activity"]][k]
        assert row["activity"] == expected["companion_activity"]
        assert row["dept"] == expected["compelled_dept"]


def test_companions_inherit_their_parents_geography(table):
    """core.py:244 -- same section and footprint as the job that compelled it."""
    companions = table.frame[table.frame["is_companion"] == 1].drop_duplicates("job_id")
    parents = table.frame[table.frame["is_companion"] == 0].drop_duplicates(
        "job_id").set_index("job_id")
    for row in companions.to_dict("records"):
        parent = parents.loc[row["parent_job_id"]]
        assert row["section_id"] == parent["section_id"]
        assert row["km_from"] == parent["km_from"]
        assert row["km_to"] == parent["km_to"]


def test_companion_protection_flags_follow_the_coded_rule(table):
    """core.py:245-248, reproduced rather than looked up: every companion takes
    a traffic block, P depends on the department and one activity exception,
    D on the department."""
    companions = table.frame[table.frame["is_companion"] == 1].drop_duplicates("job_id")
    assert (companions["needs_T"] == 1).all()
    for row in companions.to_dict("records"):
        expected_p = int(row["dept"] == "TRD"
                         and row["activity"] != "TRACTION_BOND_JUMPER")
        assert row["needs_P"] == expected_p, row["job_id"]
        assert row["needs_D"] == int(row["dept"] == "SNT"), row["job_id"]


def test_companions_carry_no_criticality_of_their_own(table):
    """core.py:249. A companion is scheduled because a rule compels it, not
    because it has urgency."""
    companions = table.frame[table.frame["is_companion"] == 1]
    assert (companions["criticality"] == 0.0).all()


def test_companions_are_not_given_attributes_core_does_not_set(table):
    """core.Job defaults resources to () (core.py:118) and has no
    min_block_min or priority field at all.

    An earlier version of this module inherited all three from the parent. That
    is a fabrication, and the resource class is the worst of them: it would have
    told a model that a companion consumes a tamper or a BCM, which the
    optimiser never believes.
    """
    companions = table.frame[table.frame["is_companion"] == 1]
    for column in ("resources", "resource_class", "min_block_min", "priority"):
        assert companions[column].isna().all(), f"{column} was invented"
    assert companions["resource_fleet_size"].isna().all()


# -- the leakage guard ------------------------------------------------------

def test_no_forbidden_column_is_a_feature(table):
    tt.assert_no_leakage(table.feature_columns)
    bare = {tt._bare(c) for c in table.feature_columns}
    assert tt.FORBIDDEN.isdisjoint(bare)


def test_the_label_and_the_keys_are_not_features(table):
    assert tt.LABEL not in table.feature_columns
    for key in tt.KEYS:
        assert key not in table.feature_columns


@pytest.mark.parametrize("column", sorted(tt.FORBIDDEN))
def test_the_guard_rejects_each_forbidden_column(column):
    """Fired, not merely present. Each name is offered as a feature and must be
    refused by itself."""
    with pytest.raises(tt.LeakageError) as exc:
        tt.assert_no_leakage(["dept", "activity", column])
    assert column in str(exc.value)


@pytest.mark.parametrize("prefix", ["activity_", "section_", "resource_", "request_"])
def test_a_join_prefix_does_not_smuggle_a_forbidden_column_past(prefix):
    """activities.csv also has duration_mean_min. Prefixing is a join
    convenience and must not become a way around the guard."""
    with pytest.raises(tt.LeakageError):
        tt.assert_no_leakage([f"{prefix}duration_mean_min"])


def test_the_two_non_obvious_leaks_are_covered():
    """block_requests.csv computes these from the label's parameters
    (dsgen/demand.py:212-213), and neither name suggests it.

        minimum_duration_min   = max(60, int(duration_mean_min))
        requested_duration_min = f(duration_mean_min, duration_sd_min)
    """
    assert "minimum_duration_min" in tt.FORBIDDEN
    assert "requested_duration_min" in tt.FORBIDDEN


def test_those_two_columns_really_are_functions_of_the_label_parameters():
    """Not taken on trust from reading the generator -- recomputed here from
    the frozen CSVs, so the claim stands on the data as shipped."""
    import numpy as np

    jobs = pd.read_csv(tt._p(tt.paths.PROCESSED_DIR, "jobs.csv"))
    requests = pd.read_csv(tt._p(tt.paths.PROCESSED_DIR, "block_requests.csv"))
    merged = jobs.merge(requests, on="job_id")

    expected_minimum = np.maximum(60, merged["duration_mean_min"].astype(int))
    assert (merged["minimum_duration_min"] == expected_minimum).all()

    req = np.ceil((merged["duration_mean_min"] + merged["duration_sd_min"]) / 30.0) * 30
    expected_requested = np.maximum(merged["min_block_min"], req)
    assert (merged["requested_duration_min"] == expected_requested).all()


def test_uncertainty_level_is_banded_off_the_label_parameters():
    """demand.py:165 bands sd/mean at 0.15 and 0.28. Excluded for the same
    reason as the parameters themselves, one step removed.

    Reproduced from the shipped CSV rather than trusted, but the CSV stores
    mean and sd ROUNDED to one decimal while the generator banded the
    unrounded values. Exactly one job sits close enough to a threshold for that
    to matter (J00034, at a rounded ratio of 0.2803 against a 0.28 cut), so the
    test allows boundary cases and requires every other row to agree. Asserting
    a clean match would have meant either misreading the data or quietly
    loosening the comparison until it passed.
    """
    jobs = pd.read_csv(tt._p(tt.paths.PROCESSED_DIR, "jobs.csv"))
    ratio = jobs["duration_sd_min"] / jobs["duration_mean_min"]
    expected = ratio.map(lambda r: "HIGH" if r > 0.28 else ("LOW" if r < 0.15
                                                            else "MEDIUM"))
    disagree = jobs["uncertainty_level"] != expected

    assert disagree.sum() <= 1, f"{disagree.sum()} rows disagree, not just rounding"
    for r in ratio[disagree]:
        assert min(abs(r - 0.15), abs(r - 0.28)) < 0.001, (
            f"ratio {r:.4f} is not near a band edge -- the derivation is wrong, "
            "not the rounding")


# -- what is left to learn --------------------------------------------------

def test_the_activity_is_still_available_as_a_feature(table):
    """The catalogue identity is legal and is the only thing the label
    actually depends on. Excluding it would leave nothing at all."""
    assert "activity" in table.feature_columns
    assert table.frame["activity"].nunique() > 1


def test_the_features_are_worth_having_at_all(table):
    """A sanity floor: the table must carry more than identity columns, or
    Phase 2 has nothing to measure."""
    assert len(table.feature_columns) >= 30
