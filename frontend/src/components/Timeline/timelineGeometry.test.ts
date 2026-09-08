import { describe, expect, it } from "vitest";
import type { SectionMeta } from "../../api/types";
import {
  BLOCK_BAR_HEIGHT,
  DAY_WIDTH,
  MINUTES_PER_DAY,
  MIN_WIDTH_FOR_RELIABILITY_LABEL,
  PX_PER_MIN,
  reliabilityLabel,
  ROW_HEIGHT,
  dayLeft,
  durationToWidth,
  minutesToX,
  orderSections,
} from "./timelineGeometry";

/** The only two block lengths the optimiser ever produces, across every scenario. */
const SHORT_BLOCK_MIN = 150;
// core.ALLOWED_BLOCK_LENGTHS. Mirrored rather than imported -- the frontend
// has no access to core.py -- and asserted against the widths it produces.
const ALLOWED_BLOCK_LENGTHS = [150, 240];

const LONG_BLOCK_MIN = 240;

function section(overrides: Partial<SectionMeta>): SectionMeta {
  return {
    section_id: "X-Y-UP",
    from_station_code: "X",
    to_station_code: "Y",
    line: "UP",
    length_km: 5,
    tracks: 2,
    electrified: true,
    is_single: false,
    headway_min: 5,
    ...overrides,
  };
}

describe("geometry constants", () => {
  it("DAY_WIDTH is derived from MINUTES_PER_DAY and PX_PER_MIN, not a separate magic number", () => {
    expect(DAY_WIDTH).toBeCloseTo(MINUTES_PER_DAY * PX_PER_MIN, 6);
  });

  /**
   * Regression: the reliability label was gated on `w > 30` while the widest
   * block the optimiser can produce was 27.6px, so the label never rendered on
   * any block in any scenario -- a dead branch, and a dead information channel
   * on the timeline. This fails if a future scale change makes it unreachable
   * again.
   */
  it("a 240-minute block is wide enough to carry its reliability label", () => {
    expect(durationToWidth(LONG_BLOCK_MIN)).toBeGreaterThanOrEqual(
      MIN_WIDTH_FOR_RELIABILITY_LABEL
    );
  });

  it("EVERY block length the planner emits carries its reliability", () => {
    // The point of the threshold change. At 34px only the 240-minute blocks
    // qualified -- 24 of the reference plan's 140 -- and those are the ones
    // with the most slack, so the only figure ever on screen was 1.00 and the
    // timeline read as though every block were certain.
    for (const minutes of ALLOWED_BLOCK_LENGTHS) {
      expect(durationToWidth(minutes)).toBeGreaterThanOrEqual(
        MIN_WIDTH_FOR_RELIABILITY_LABEL
      );
    }
  });

  it("the label threshold leaves real padding rather than running edge to edge", () => {
    // ".90" at the 9px label size is ~15px wide -- the leading zero is dropped
    // precisely to buy the width that admits a 150-minute block.
    const APPROX_LABEL_TEXT_WIDTH = 15;
    expect(MIN_WIDTH_FOR_RELIABILITY_LABEL).toBeGreaterThan(APPROX_LABEL_TEXT_WIDTH + 4);
  });

  it("renders reliability without a leading zero, and 1.00 as 1.0", () => {
    expect(reliabilityLabel(0.9)).toBe(".90");
    expect(reliabilityLabel(0.874)).toBe(".87");
    expect(reliabilityLabel(1)).toBe("1.0");
    expect(reliabilityLabel(0.999)).toBe("1.0");
    // Three characters at most, or the width budget above is wrong.
    for (const r of [0, 0.03, 0.5, 0.94, 0.995, 1]) {
      expect(reliabilityLabel(r).length).toBeLessThanOrEqual(3);
    }
  });

  it("splits the bar height evenly for every bundle size that occurs", () => {
    // 1, 2 and 3 departments are the only bundle sizes in any scenario.
    expect(BLOCK_BAR_HEIGHT % 3).toBe(0);
    expect(BLOCK_BAR_HEIGHT / 3).toBeGreaterThanOrEqual(6);
  });

  it("leaves the bar clear of the row separators above and below", () => {
    expect(ROW_HEIGHT).toBeGreaterThan(BLOCK_BAR_HEIGHT);
    expect((ROW_HEIGHT - BLOCK_BAR_HEIGHT) / 2).toBeGreaterThanOrEqual(2);
  });

  /**
   * Two blocks on the same section and day never overlap in time, and x is a
   * linear map of time, so no scale can make their bars overlap. Pins the
   * linearity that guarantee rests on.
   */
  it("maps time to x linearly, so non-overlapping blocks can never be drawn overlapping", () => {
    const firstEnds = minutesToX(3, 300) + durationToWidth(SHORT_BLOCK_MIN);
    const secondStarts = minutesToX(3, 300 + SHORT_BLOCK_MIN);
    expect(firstEnds).toBeCloseTo(secondStarts, 6);
  });
});

describe("dayLeft / minutesToX / durationToWidth", () => {
  it("places minute 0 of day 0 at the origin", () => {
    expect(minutesToX(0, 0)).toBe(0);
  });

  it("advances by exactly one DAY_WIDTH per day, independent of minute offset", () => {
    expect(minutesToX(1, 0) - minutesToX(0, 0)).toBeCloseTo(DAY_WIDTH, 6);
    expect(dayLeft(3)).toBeCloseTo(3 * DAY_WIDTH, 6);
  });

  it("a 240-minute block is wider than a 150-minute block in the same proportion as their durations", () => {
    const w240 = durationToWidth(240);
    const w150 = durationToWidth(150);
    expect(w240 / w150).toBeCloseTo(240 / 150, 6);
  });
});

describe("orderSections", () => {
  it("orders by the FROM station's sequence, so rows read in physical corridor order", () => {
    const stationSeq = new Map([
      ["C", 2],
      ["A", 0],
      ["B", 1],
    ]);
    const sections = [
      section({ section_id: "B-C-UP", from_station_code: "B", line: "UP" }),
      section({ section_id: "A-B-DN", from_station_code: "A", line: "DN" }),
      section({ section_id: "A-B-UP", from_station_code: "A", line: "UP" }),
    ];
    const ordered = orderSections(sections, stationSeq);
    expect(ordered.map((s) => s.section_id)).toEqual(["A-B-DN", "A-B-UP", "B-C-UP"]);
  });

  it("breaks ties at the same station by line name, so DN/UP order is deterministic", () => {
    const stationSeq = new Map([["A", 0]]);
    const sections = [
      section({ section_id: "A-Z-UP", from_station_code: "A", line: "UP" }),
      section({ section_id: "A-Z-DN", from_station_code: "A", line: "DN" }),
    ];
    const ordered = orderSections(sections, stationSeq);
    // "DN" < "UP" lexically -- asserting the actual tie-break, not just "some order".
    expect(ordered.map((s) => s.line)).toEqual(["DN", "UP"]);
  });

  it("does not mutate the input array", () => {
    const stationSeq = new Map([["A", 0], ["B", 1]]);
    const sections = [
      section({ section_id: "B-Z", from_station_code: "B" }),
      section({ section_id: "A-Z", from_station_code: "A" }),
    ];
    const original = [...sections];
    orderSections(sections, stationSeq);
    expect(sections).toEqual(original);
  });
});
