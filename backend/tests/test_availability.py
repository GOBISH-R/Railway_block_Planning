"""Asset availability: the named metric, and the guards that stop it lying.

The metric itself is one division. Almost everything here is about the two ways
it misleads, both of which are easy to hit by accident:

  * it is maximised by doing no maintenance, so it must never appear without
    the work figure beside it;
  * it cannot tell 03:00 from 08:00, so a plan can look competitive on
    availability while causing two and a half times the delay -- which is
    exactly what B2 Fixed-calendar does in the frozen benchmark.

Reading a plan changes nothing, so there is no frozen-plan gate to worry about
here beyond the one asserted at the end.
"""
from __future__ import annotations

import pytest

from blockplan_service import availability as av

CORRIDOR_LINES = 52
HORIZON = 14
CAPACITY = CORRIDOR_LINES * HORIZON * 1440          # 1,048,320 minutes


def block(section_id: str, length: int) -> dict:
    return {"section_id": section_id, "length": length}


# -- the arithmetic ----------------------------------------------------------

def test_the_denominator_is_section_lines_not_station_pairs():
    """Blocking JTJ-TPT-UP does not block JTJ-TPT-DN. Counting the 26 station
    pairs instead of the 52 section-lines would double every block's apparent
    cost and describe a single-line corridor."""
    assert av.capacity_minutes(CORRIDOR_LINES, HORIZON) == CAPACITY
    assert len(av._frozen_section_ids()) == CORRIDOR_LINES


def test_an_empty_plan_is_fully_available():
    report = av.from_blocks([], section_ids=["A-B-UP"], horizon_days=HORIZON,
                            jobs_done=0, jobs_deferred=175,
                            traffic_delay_minutes=0.0)
    assert report.availability == 1.0
    assert report.occupied_share == 0.0


def test_availability_is_one_minus_the_occupied_share():
    report = av.from_blocks(
        [block("A-B-UP", 720), block("A-B-UP", 720)],
        section_ids=["A-B-UP"], horizon_days=1,
        jobs_done=2, jobs_deferred=0, traffic_delay_minutes=0.0)
    # 1440 of 1440 minutes on the only section-line
    assert report.block_minutes == 1440
    assert report.availability == pytest.approx(0.0)
    assert report.occupied_share == pytest.approx(1.0)


def test_blocks_are_attributed_to_their_own_section_line():
    report = av.from_blocks(
        [block("A-B-UP", 150), block("A-B-UP", 240), block("A-B-DN", 150)],
        section_ids=["A-B-UP", "A-B-DN", "C-D-UP"], horizon_days=HORIZON,
        jobs_done=3, jobs_deferred=0, traffic_delay_minutes=0.0)

    assert report.by_section["A-B-UP"].block_minutes == 390
    assert report.by_section["A-B-DN"].block_minutes == 150
    assert report.by_section["C-D-UP"].block_minutes == 0
    assert report.by_section["C-D-UP"].availability == 1.0
    assert report.busiest_sections[0].section_id == "A-B-UP"


def test_the_section_breakdown_is_serialised_busiest_first():
    """Computed since the metric existed, published only now.

    Order is the useful part: which stretches of the corridor actually gave up
    time. Sections with no blocks stay in the list, because their availability
    of 1.0 is a fact about the plan, not an absence of data.
    """
    report = av.from_blocks(
        [block("A-B-UP", 240), block("A-B-UP", 150), block("C-D-UP", 150)],
        section_ids=["A-B-UP", "C-D-UP", "E-F-UP"], horizon_days=HORIZON,
        jobs_done=3, jobs_deferred=0, traffic_delay_minutes=0.0)
    rows = report.as_dict()["by_section"]

    assert [r["section_id"] for r in rows] == ["A-B-UP", "C-D-UP", "E-F-UP"]
    assert [r["block_minutes"] for r in rows] == [390, 150, 0]
    assert rows[0]["blocks"] == 2
    assert rows[-1]["availability"] == 1.0
    assert set(rows[0]) == {"section_id", "blocks", "block_minutes",
                            "block_hours", "availability"}


def test_the_section_breakdown_reconciles_with_the_corridor_total():
    """A breakdown that does not add up to the headline would be worse than
    none at all."""
    report = av.from_blocks(
        [block("A-B-UP", 240), block("C-D-UP", 150)],
        section_ids=["A-B-UP", "C-D-UP"], horizon_days=HORIZON,
        jobs_done=2, jobs_deferred=0, traffic_delay_minutes=0.0)
    payload = report.as_dict()

    assert sum(r["block_minutes"] for r in payload["by_section"]) == \
        payload["block_minutes"]
    assert len(payload["by_section"]) == payload["section_lines"]


def test_the_frozen_method_reports_carry_no_section_breakdown():
    """The benchmark artefacts record no section for their blocks, so the list
    is empty rather than fabricated."""
    for report in av.from_frozen_artefacts().values():
        assert report.as_dict()["by_section"] == []


def test_a_section_with_no_blocks_still_counts_in_the_denominator():
    """Otherwise a plan that concentrated all its work on two section-lines
    would score better than one that spread it evenly."""
    report = av.from_blocks(
        [block("A-B-UP", 1440)],
        section_ids=["A-B-UP", "C-D-UP"], horizon_days=1,
        jobs_done=1, jobs_deferred=0, traffic_delay_minutes=0.0)
    assert report.section_lines == 2
    assert report.availability == pytest.approx(0.5)


def test_weighted_movements_respect_the_day_mask():
    class Train:
        def __init__(self, klass, mask):
            self.klass, self.day_mask = klass, mask

    weights = {"EXPRESS": 2.0, "FREIGHT": 1.0}
    daily = av.weighted_movements([Train("EXPRESS", 127)], 14, weights)
    weekly = av.weighted_movements([Train("EXPRESS", 0b0000001)], 14, weights)

    assert daily == pytest.approx(2.0 * 14)
    assert weekly == pytest.approx(2.0 * 2), "one day in seven, twice in 14"


# -- the trap: availability must never travel alone --------------------------

def test_doing_nothing_scores_perfectly_which_is_why_the_work_figure_is_required():
    """The metric's central weakness, asserted rather than described. A plan
    that defers every job is the best possible plan by availability alone."""
    nothing = av.from_blocks([], section_ids=["A-B-UP"], horizon_days=HORIZON,
                             jobs_done=0, jobs_deferred=175,
                             traffic_delay_minutes=0.0)
    assert nothing.availability == 1.0
    assert "completing 0 of 175 jobs" in nothing.headline()


def test_the_headline_cannot_be_rendered_without_the_work_figure():
    report = av.from_blocks([block("A-B-UP", 150)], section_ids=["A-B-UP"],
                            horizon_days=HORIZON, jobs_done=174,
                            jobs_deferred=1, traffic_delay_minutes=299.2)
    headline = report.headline()
    assert "%" in headline
    assert "174 of 175 jobs" in headline
    assert "section-hours" in headline


def test_jobs_done_and_deferred_are_required_fields():
    """Not defaulted. A report that could be built without them would sooner or
    later be quoted without them."""
    with pytest.raises(TypeError):
        av.AvailabilityReport(                     # type: ignore[call-arg]
            horizon_days=14, section_lines=52, capacity_minutes=CAPACITY,
            block_minutes=0, blocks=0, traffic_delay_minutes=0.0,
            weighted_movements=0.0)


def test_the_dict_form_carries_the_work_figures_too():
    report = av.from_blocks([block("A-B-UP", 150)], section_ids=["A-B-UP"],
                            horizon_days=HORIZON, jobs_done=174,
                            jobs_deferred=1, traffic_delay_minutes=299.2)
    payload = report.as_dict()
    for key in ("availability", "jobs_done", "jobs_deferred",
                "traffic_delay_minutes", "headline"):
        assert key in payload


# -- the trap: availability cannot tell 03:00 from 08:00 ---------------------

def test_the_frozen_methods_rank_as_measured():
    reports = av.from_frozen_artefacts()
    assert len(reports) == 6
    order = [name for name, _ in sorted(reports.items(),
                                        key=lambda kv: -kv[1].availability)]
    assert order[0] == "B4 Bundle-only"
    assert order[1] == "OURS"
    assert order[-1] == "B3 Greedy-earliest"


def test_availability_alone_would_flatter_the_fixed_calendar_baseline():
    """The reason traffic delay is reported beside it.

    B2 ranks third of six on availability while causing 743.4 weighted
    delay-minutes against OURS' 299.2 -- two and a half times the disruption
    from a plan that looks competitive on this metric. Anyone quoting
    availability without the delay column would be making that mistake.
    """
    reports = av.from_frozen_artefacts()
    b2, ours = reports["B2 Fixed-calendar"], reports["OURS"]

    assert b2.availability < ours.availability
    assert b2.block_minutes > ours.block_minutes
    assert b2.traffic_delay_minutes > 2.4 * ours.traffic_delay_minutes
    assert b2.jobs_done >= ours.jobs_done, "and it completes no less work"


def test_the_delay_is_not_dressed_up_as_a_second_availability():
    """Reported in weighted delay-minutes, normalised only per weighted
    movement. There is no total-scheduled-train-minutes denominator in this
    model, and inventing one would make the number worse."""
    payload = av.from_blocks(
        [block("A-B-UP", 150)], section_ids=["A-B-UP"], horizon_days=HORIZON,
        jobs_done=1, jobs_deferred=0, traffic_delay_minutes=299.2,
        weighted_movements_total=73376.8).as_dict()

    assert payload["traffic_delay_minutes"] == 299.2
    assert payload["delay_per_weighted_movement"] == pytest.approx(
        299.2 / 73376.8, rel=1e-3)
    assert not any("availability" in k and "traffic" in k for k in payload)


# -- before and after --------------------------------------------------------

def test_the_improvement_over_dept_wise_practice():
    """The claim the Evidence screen will make, pinned to the frozen numbers."""
    reports = av.from_frozen_artefacts()
    result = av.improvement(reports["B0 Dept-wise, no reliability"],
                            reports["OURS"])

    assert result["jobs_gained"] == 13
    assert result["section_hours_released"] == pytest.approx(58.5)
    assert result["availability_gain"] == pytest.approx(0.00335, abs=1e-5)
    assert result["traffic_delay_after"] < result["traffic_delay_before"]
    assert "+13 jobs" in result["headline"]


def test_the_improvement_reports_work_as_well_as_time():
    """Releasing line time by deferring jobs is a smaller plan, not a better
    one, so the comparison always carries both."""
    reports = av.from_frozen_artefacts()
    result = av.improvement(reports["B3 Greedy-earliest"], reports["OURS"])
    assert "jobs_done_before" in result and "jobs_done_after" in result


# -- the live plan -----------------------------------------------------------

@pytest.mark.slow
def test_the_reference_plan_availability(service):
    """Computed from the plan the app actually serves."""
    from test_reference_plan import REFERENCE_PLAN_ID, REFERENCE_REQUEST

    plan = service.plan(REFERENCE_REQUEST)
    assert plan["plan_id"] == REFERENCE_PLAN_ID

    report = av.for_plan(plan, service.context)
    assert report.section_lines == CORRIDOR_LINES
    assert report.capacity_minutes == CAPACITY
    assert report.block_minutes == 23160
    assert report.availability == pytest.approx(0.97791, abs=1e-5)
    assert report.jobs_done == 174 and report.jobs_deferred == 1
    assert report.traffic_delay_minutes == 299.2


@pytest.mark.slow
def test_the_live_plan_and_the_frozen_artefact_disagree_by_one_block(service):
    """Recorded so it cannot surprise anyone on demo day.

    Same plan id, same objective, same traffic cost, same block fingerprint --
    and a different block LENGTH distribution: the artefact has 115 blocks of
    150 minutes and 25 of 240, the live plan 116 and 24. Ninety minutes,
    availability differing in the fifth decimal.

    This is the solver tie-breaking documented for block count and
    utilisation; length distribution is the same kind of quantity. If this test
    ever fails, the two have converged or diverged further, and either is worth
    knowing before a judge finds it.
    """
    from test_reference_plan import REFERENCE_REQUEST

    live = av.for_plan(service.plan(REFERENCE_REQUEST), service.context)
    frozen = av.from_frozen_artefacts()["OURS"]

    assert live.blocks == frozen.blocks == 140
    assert live.jobs_done == frozen.jobs_done
    assert live.traffic_delay_minutes == frozen.traffic_delay_minutes
    assert frozen.block_minutes - live.block_minutes == 90
    assert abs(live.availability - frozen.availability) < 1e-4


def test_reading_a_plan_does_not_change_it(service):
    """The metric is derived. If it mutated the plan the frozen gate would
    start failing intermittently, which is the worst way to find out."""
    from test_reference_plan import REFERENCE_REQUEST

    plan = service.plan(REFERENCE_REQUEST)
    before = (plan["plan_id"], plan["objective"], len(plan["blocks"]),
              [b["length"] for b in plan["blocks"]])

    av.for_plan(plan, service.context)

    assert (plan["plan_id"], plan["objective"], len(plan["blocks"]),
            [b["length"] for b in plan["blocks"]]) == before
