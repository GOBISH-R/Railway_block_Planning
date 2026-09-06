import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CorridorResponse, Dept, PlanBlock, SectionMeta, Station } from "../../api/types";
import { TimelineOverview } from "./TimelineOverview";
import {
  OVERVIEW_HEADER_HEIGHT,
  OVERVIEW_ROW_HEIGHT,
  OVERVIEW_WIDTH,
  orderSections,
  overviewHeight,
} from "./timelineGeometry";

const HORIZON_DAYS = 14;
const SECTION_COUNT = 52;

function station(code: string, seq: number): Station {
  return { station_code: code, station_name: code, latitude: 0, longitude: 0, seq, is_junction: false };
}

function section(id: string, from: string, to: string, line: string): SectionMeta {
  return {
    section_id: id, from_station_code: from, to_station_code: to, line,
    length_km: 5, tracks: 2, electrified: true, is_single: false, headway_min: 5,
  };
}

const SECTIONS: SectionMeta[] = Array.from({ length: SECTION_COUNT }, (_, i) =>
  section(`S${i}-UP`, `ST${Math.floor(i / 2)}`, `ST${Math.floor(i / 2) + 1}`, i % 2 ? "UP" : "DN")
);
const STATIONS: Station[] = Array.from({ length: 27 }, (_, i) => station(`ST${i}`, i));
const CORRIDOR: CorridorResponse = { stations: STATIONS, sections: SECTIONS };

function block(id: string, sectionId: string, day: number, deptMix: Dept[], overrides: Partial<PlanBlock> = {}): PlanBlock {
  return {
    block_id: id, section_id: sectionId, day, start_min: 540, length: 150, end_min: 690,
    reliability: 0.97, traffic_cost: 4.2, exp_overrun_cost: 0.5,
    dept_mix: deptMix, job_ids: ["J1"], ...overrides,
  };
}

/** One block on every day and spread across many sections, some bundled. */
const BLOCKS: PlanBlock[] = Array.from({ length: HORIZON_DAYS }, (_, day) =>
  block(
    `B${String(day).padStart(4, "0")}`,
    SECTIONS[day * 3].section_id,
    day,
    day % 3 === 0 ? ["ENGG", "SNT", "TRD"] : ["ENGG"]
  )
);

function renderOverview(blocks: PlanBlock[] = BLOCKS) {
  const { container } = render(
    <TimelineOverview corridor={CORRIDOR} blocks={blocks} horizonDays={HORIZON_DAYS} />
  );
  return container;
}

/**
 * A block ending exactly at midnight on the final day lands exactly on the
 * right edge, where `day * (W/days) + (1440/1440) * (W/days)` comes back as
 * 900.0000000000001. That is float representation, not overflow, so the edge
 * assertions carry a tolerance rather than the geometry carrying a clamp --
 * a clamp would silently absorb a real overflow if one were ever introduced.
 */
const EDGE_EPSILON = 1e-6;

function marks(container: HTMLElement) {
  return Array.from(container.querySelectorAll(".toverview__mark")).map((r) => ({
    x: Number(r.getAttribute("x")),
    y: Number(r.getAttribute("y")),
    w: Number(r.getAttribute("width")),
    multi: r.classList.contains("toverview__mark--multi"),
  }));
}

describe("TimelineOverview coverage", () => {
  it("represents the whole plan: every block is drawn, none scrolled away", () => {
    const container = renderOverview();
    expect(marks(container)).toHaveLength(BLOCKS.length);
  });

  it("sizes the viewBox for all 52 section-lines, so no row is cut off", () => {
    const container = renderOverview();
    const [, , width, height] = container
      .querySelector("svg")!
      .getAttribute("viewBox")!
      .split(/\s+/)
      .map(Number);

    expect(width).toBe(OVERVIEW_WIDTH);
    expect(height).toBe(overviewHeight(SECTION_COUNT));
    expect(height).toBe(OVERVIEW_HEADER_HEIGHT + SECTION_COUNT * OVERVIEW_ROW_HEIGHT);
  });

  it("draws all 14 days across the full width, with a boundary closing the last", () => {
    const container = renderOverview();
    expect(container.querySelectorAll(".toverview__day-label")).toHaveLength(HORIZON_DAYS);
    expect(container.querySelectorAll(".toverview__day-boundary")).toHaveLength(HORIZON_DAYS + 1);

    const labels = Array.from(container.querySelectorAll(".toverview__day-label"));
    expect(labels.map((t) => t.textContent)).toEqual(
      Array.from({ length: HORIZON_DAYS }, (_, d) => String(d))
    );
  });

  it("keeps every mark inside the viewBox", () => {
    const container = renderOverview();
    const height = overviewHeight(SECTION_COUNT);
    for (const m of marks(container)) {
      expect(m.x).toBeGreaterThanOrEqual(0);
      expect(m.x + m.w).toBeLessThanOrEqual(OVERVIEW_WIDTH + EDGE_EPSILON);
      expect(m.y).toBeGreaterThanOrEqual(OVERVIEW_HEADER_HEIGHT);
      expect(m.y + OVERVIEW_ROW_HEIGHT).toBeLessThanOrEqual(height);
    }
  });

  it("places a block on the last day and last section without overflowing", () => {
    const last = block("BLAST", SECTIONS[SECTION_COUNT - 1].section_id, HORIZON_DAYS - 1, ["ENGG"], {
      start_min: 1290, length: 150, end_min: 1440,
    });
    const [m] = marks(renderOverview([last]));
    expect(m.x + m.w).toBeLessThanOrEqual(OVERVIEW_WIDTH + EDGE_EPSILON);
    expect(m.y).toBe(OVERVIEW_HEADER_HEIGHT + (SECTION_COUNT - 1) * OVERVIEW_ROW_HEIGHT);
  });
});

describe("TimelineOverview multi-department emphasis", () => {
  it("marks multi-department blocks distinctly from single-department ones", () => {
    const container = renderOverview([
      block("B1", SECTIONS[0].section_id, 0, ["ENGG"]),
      block("B2", SECTIONS[1].section_id, 0, ["ENGG", "SNT"]),
      block("B3", SECTIONS[2].section_id, 0, ["ENGG", "SNT", "TRD"]),
    ]);
    const drawn = marks(container);
    expect(drawn.filter((m) => m.multi)).toHaveLength(2);
    expect(drawn.filter((m) => !m.multi)).toHaveLength(1);
  });

  it("paints multi-department marks last so a neighbouring row cannot hide them", () => {
    const container = renderOverview([
      block("B1", SECTIONS[0].section_id, 0, ["ENGG", "SNT"]),
      block("B2", SECTIONS[1].section_id, 0, ["ENGG"]),
    ]);
    const drawn = marks(container);
    // Document order is paint order in SVG: the single-department mark comes first.
    expect(drawn[0].multi).toBe(false);
    expect(drawn[drawn.length - 1].multi).toBe(true);
  });

  it("counts the bundled blocks in the key and the accessible name", () => {
    const container = renderOverview();
    const expectedMulti = BLOCKS.filter((b) => b.dept_mix.length > 1).length;
    expect(container.textContent).toContain(`multi-department (${expectedMulti})`);
    expect(container.querySelector("svg")!.getAttribute("aria-label")).toContain(
      `${expectedMulti} carry more than one department`
    );
  });
});

describe("TimelineOverview row order", () => {
  it("uses the same section order as the detailed grid, by construction", () => {
    const stationSeq = new Map(STATIONS.map((s) => [s.station_code, s.seq]));
    const ordered = orderSections(SECTIONS, stationSeq);

    // A block on the Nth section of that shared ordering lands on the Nth row.
    const nth = 7;
    const [m] = marks(renderOverview([block("BX", ordered[nth].section_id, 0, ["ENGG"])]));
    expect(m.y).toBe(OVERVIEW_HEADER_HEIGHT + nth * OVERVIEW_ROW_HEIGHT);
  });

  it("ignores a block whose section is not on the corridor rather than throwing", () => {
    const container = renderOverview([block("BX", "NOT-A-SECTION", 0, ["ENGG"])]);
    expect(marks(container)).toHaveLength(0);
  });

  it("renders an empty plan without marks and without crashing", () => {
    const container = renderOverview([]);
    expect(marks(container)).toHaveLength(0);
    expect(container.querySelectorAll(".toverview__day-label")).toHaveLength(HORIZON_DAYS);
  });
});
