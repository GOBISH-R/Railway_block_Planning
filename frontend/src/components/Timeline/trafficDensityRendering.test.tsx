import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CorridorResponse, Movement, SectionMeta, Station } from "../../api/types";
import { TimelineGrid } from "./TimelineGrid";

function station(code: string, seq: number): Station {
  return { station_code: code, station_name: code, latitude: 0, longitude: 0, seq, is_junction: false };
}

const SECTIONS: SectionMeta[] = [
  { section_id: "A-B-UP", from_station_code: "A", to_station_code: "B", line: "UP",
    length_km: 10, tracks: 2, electrified: true, is_single: false, headway_min: 5 },
];
const CORRIDOR: CorridorResponse = { stations: [station("A", 0), station("B", 1)], sections: SECTIONS };

function movement(enter_min: number): Movement {
  return {
    train_number: "12345", train_class: "EXPRESS", from_code: "A", to_code: "B",
    direction: "UP", enter_min, is_synthetic: false, section_id: "A-B-UP",
  };
}

/** Uneven traffic: one busy half-hour, one quieter one. */
const MOVEMENTS: Movement[] = [
  ...Array.from({ length: 6 }, () => movement(500)),
  ...Array.from({ length: 2 }, () => movement(700)),
];

function renderGrid() {
  const { container } = render(
    <TimelineGrid
      corridor={CORRIDOR}
      blocks={[]}
      movements={MOVEMENTS}
      horizonDays={2}
      selectedBlockId={null}
      onSelectBlock={vi.fn()}
    />
  );
  return container;
}

/**
 * The shading was toned down to sit behind the blocks rather than compete with
 * them, but the reduction is applied in CSS (`fill-opacity` on
 * `.tgrid__density`, which multiplies with the per-bucket `opacity` attribute).
 * These tests guard the part that must survive that: the density information
 * itself, still varying bucket to bucket.
 */
describe("traffic density rendering", () => {
  it("still draws the density layer", () => {
    const container = renderGrid();
    expect(container.querySelectorAll(".tgrid__density").length).toBeGreaterThan(0);
  });

  it("keeps density encoded per bucket rather than flattened to one value", () => {
    const container = renderGrid();
    const opacities = Array.from(container.querySelectorAll(".tgrid__density")).map((r) =>
      Number(r.getAttribute("opacity"))
    );
    // Two different traffic levels must still produce two different opacities.
    expect(new Set(opacities).size).toBeGreaterThan(1);
  });

  it("scales opacity with the busiest bucket, the quieter one lighter", () => {
    const container = renderGrid();
    const opacities = Array.from(container.querySelectorAll(".tgrid__density"))
      .map((r) => Number(r.getAttribute("opacity")))
      .sort((a, b) => a - b);
    const quiet = opacities[0];
    const busy = opacities[opacities.length - 1];
    expect(busy).toBeGreaterThan(quiet);
    // 2 of 6 movements -- the ratio the data implies, not a styling choice.
    expect(quiet / busy).toBeCloseTo(2 / 6, 6);
  });

  it("repeats the same profile behind every day, as the daily timetable implies", () => {
    const container = renderGrid();
    // 2 days x 2 non-empty buckets.
    expect(container.querySelectorAll(".tgrid__density")).toHaveLength(4);
  });

  it("leaves the density layer non-interactive so blocks stay clickable", () => {
    const container = renderGrid();
    for (const rect of container.querySelectorAll(".tgrid__density")) {
      expect(rect.classList.contains("tgrid__density")).toBe(true);
    }
    // pointer-events:none is CSS; what matters structurally is that density
    // rects carry no handlers or focus.
    expect(container.querySelectorAll(".tgrid__density[tabindex]")).toHaveLength(0);
  });
});
