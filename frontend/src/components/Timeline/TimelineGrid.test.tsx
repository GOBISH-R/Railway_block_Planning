import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CorridorResponse, PlanBlock, SectionMeta, Station } from "../../api/types";
import { TimelineGrid } from "./TimelineGrid";
import {
  BLOCK_BAR_HEIGHT,
  DAY_WIDTH,
  MIN_WIDTH_FOR_RELIABILITY_LABEL,
  ROW_HEIGHT,
  durationToWidth,
} from "./timelineGeometry";

const HORIZON_DAYS = 14;

function station(code: string, seq: number): Station {
  return {
    station_code: code,
    station_name: code,
    latitude: 0,
    longitude: 0,
    seq,
    is_junction: false,
  };
}

function section(id: string, from: string, to: string, line: string): SectionMeta {
  return {
    section_id: id,
    from_station_code: from,
    to_station_code: to,
    line,
    length_km: 5,
    tracks: 2,
    electrified: true,
    is_single: false,
    headway_min: 5,
  };
}

/** 52 section-lines, matching the real corridor's row count. */
const SECTIONS: SectionMeta[] = Array.from({ length: 52 }, (_, i) =>
  section(`S${i}-UP`, `ST${Math.floor(i / 2)}`, `ST${Math.floor(i / 2) + 1}`, i % 2 ? "UP" : "DN")
);
const BLOCK_SECTION_ID = SECTIONS[4].section_id;

function block(overrides: Partial<PlanBlock> = {}): PlanBlock {
  return {
    block_id: "B0010",
    section_id: BLOCK_SECTION_ID,
    day: 2,
    start_min: 540,
    length: 150,
    end_min: 690,
    reliability: 0.97,
    traffic_cost: 4.2,
    exp_overrun_cost: 0.5,
    dept_mix: ["ENGG", "SNT", "TRD"],
    job_ids: ["J1", "J2", "J3"],
    ...overrides,
  };
}

const STATIONS: Station[] = Array.from({ length: 27 }, (_, i) => station(`ST${i}`, i));
const CORRIDOR: CorridorResponse = { stations: STATIONS, sections: SECTIONS };

function renderGrid(blocks: PlanBlock[]) {
  const { container } = render(
    <TimelineGrid
      corridor={CORRIDOR}
      blocks={blocks}
      movements={[]}
      horizonDays={HORIZON_DAYS}
      selectedBlockId={null}
      onSelectBlock={vi.fn()}
    />
  );
  return container;
}

/** The department rects of a block group, in render order. */
function bandsOf(container: HTMLElement) {
  const group = container.querySelector(".tgrid__block")!;
  return Array.from(group.querySelectorAll("rect"))
    .filter((r) => !r.classList.contains("tgrid__block-outline"))
    .map((r) => ({
      x: Number(r.getAttribute("x")),
      y: Number(r.getAttribute("y")),
      w: Number(r.getAttribute("width")),
      h: Number(r.getAttribute("height")),
    }));
}

describe("TimelineGrid department bands", () => {
  /**
   * Departments used to be drawn as side-by-side vertical stripes, which
   * subdivided the block's width -- the axis already carrying 14 days of time.
   * A three-department 150-minute block became three ~6px slivers that read as
   * three separate narrow blocks. They are now full-width horizontal bands.
   */
  it("gives every department in a 3-department block the block's full width", () => {
    const container = renderGrid([block({ dept_mix: ["ENGG", "SNT", "TRD"] })]);
    const bands = bandsOf(container);
    const expectedWidth = durationToWidth(150);

    expect(bands).toHaveLength(3);
    for (const b of bands) {
      expect(b.w).toBeCloseTo(expectedWidth, 6);
    }
    // All three start at the same x -- they are stacked, not side by side.
    expect(new Set(bands.map((b) => b.x)).size).toBe(1);
  });

  it("stacks the bands so they tile the bar height exactly, without gaps or overlap", () => {
    const container = renderGrid([block({ dept_mix: ["ENGG", "SNT", "TRD"] })]);
    const bands = bandsOf(container);

    const top = Math.min(...bands.map((b) => b.y));
    const bottom = Math.max(...bands.map((b) => b.y + b.h));
    expect(bottom - top).toBeCloseTo(BLOCK_BAR_HEIGHT, 6);

    const sorted = [...bands].sort((a, b) => a.y - b.y);
    for (let i = 0; i < sorted.length - 1; i++) {
      expect(sorted[i].y + sorted[i].h).toBeCloseTo(sorted[i + 1].y, 6);
    }
    for (const b of bands) {
      expect(b.h).toBeCloseTo(BLOCK_BAR_HEIGHT / 3, 6);
    }
  });

  it("draws a single-department block as one full-height bar", () => {
    const container = renderGrid([block({ dept_mix: ["ENGG"] })]);
    const bands = bandsOf(container);
    expect(bands).toHaveLength(1);
    expect(bands[0].h).toBeCloseTo(BLOCK_BAR_HEIGHT, 6);
  });

  it("keeps each band thick enough to read", () => {
    const container = renderGrid([block({ dept_mix: ["ENGG", "SNT", "TRD"] })]);
    for (const b of bandsOf(container)) {
      expect(b.h).toBeGreaterThanOrEqual(6);
    }
  });
});

describe("TimelineGrid reliability label", () => {
  /**
   * Regression, twice over. The label was first gated on `w > 30` when the
   * widest possible block was 27.6px, so it never rendered at all. The
   * threshold then went to 34px, which a 240-minute block clears (38.4px) and
   * a 150-minute one does not (24.0px) -- and since long blocks carry the most
   * slack, the only reliability figure ever visible on the timeline was 1.00.
   * The plan being demonstrated is 116 short blocks and 24 long ones, so that
   * read as "every block is certain" while the short ones sat at 0.90.
   */
  it("renders the reliability figure on a 240-minute block", () => {
    const container = renderGrid([block({ length: 240, end_min: 780, reliability: 0.94 })]);
    const label = container.querySelector(".tgrid__block-label");
    expect(label).not.toBeNull();
    expect(label!.textContent).toBe(".94");
  });

  it("renders it on a 150-minute block too, which is most of the plan", () => {
    const container = renderGrid([block({ length: 150, reliability: 0.9 })]);
    const label = container.querySelector(".tgrid__block-label");
    expect(label).not.toBeNull();
    expect(label!.textContent).toBe(".90");
    expect(durationToWidth(150)).toBeGreaterThanOrEqual(MIN_WIDTH_FOR_RELIABILITY_LABEL);
  });

  it("centres the label on the bar rather than inside one department's band", () => {
    const container = renderGrid([block({ length: 240, end_min: 780 })]);
    const label = container.querySelector(".tgrid__block-label")!;
    const bar = bandsOf(container)[0];
    expect(Number(label.getAttribute("x"))).toBeCloseTo(bar.x + durationToWidth(240) / 2, 6);
    expect(label.getAttribute("text-anchor")).toBe("middle");
  });

  it("still exposes reliability for every block through the accessible name", () => {
    const container = renderGrid([block({ length: 150, reliability: 0.88 })]);
    const group = container.querySelector(".tgrid__block")!;
    expect(group.getAttribute("aria-label")).toContain("reliability 0.88");
  });
});

describe("TimelineGrid structure", () => {
  it("keeps one row per section-line and one column per horizon day", () => {
    const container = renderGrid([block()]);
    expect(container.querySelectorAll(".tgrid__label-row")).toHaveLength(52);

    const body = container.querySelector(".tgrid__body-svg")!;
    expect(Number(body.getAttribute("height"))).toBeCloseTo(52 * ROW_HEIGHT, 6);
    expect(Number(body.getAttribute("width"))).toBeCloseTo(HORIZON_DAYS * DAY_WIDTH, 6);
  });

  it("keeps the block interactive and keyboard-reachable", () => {
    const container = renderGrid([block()]);
    const group = container.querySelector(".tgrid__block")!;
    expect(group.getAttribute("role")).toBe("button");
    expect(group.getAttribute("tabindex")).toBe("0");
  });
});
