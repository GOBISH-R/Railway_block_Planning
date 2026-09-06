import { describe, expect, it } from "vitest";
import type { Movement } from "../../api/types";
import { BUCKETS_PER_DAY, computeDensityBySection } from "./trafficDensity";

function movement(overrides: Partial<Movement>): Movement {
  return {
    train_number: "1",
    train_class: "EXPRESS",
    from_code: "A",
    to_code: "B",
    direction: "UP",
    enter_min: 0,
    is_synthetic: false,
    section_id: "A-B-UP",
    ...overrides,
  };
}

describe("computeDensityBySection", () => {
  it("buckets movements into 30-minute bins and counts per section", () => {
    const density = computeDensityBySection([
      movement({ section_id: "A-B-UP", enter_min: 10 }),
      movement({ section_id: "A-B-UP", enter_min: 20 }), // same 30-min bucket as above
      movement({ section_id: "A-B-UP", enter_min: 45 }), // next bucket
    ]);
    const buckets = density.get("A-B-UP")!;
    expect(buckets[0]).toBe(2);
    expect(buckets[1]).toBe(1);
    expect(buckets.length).toBe(BUCKETS_PER_DAY);
  });

  it("keeps sections independent -- one section's traffic never inflates another's", () => {
    const density = computeDensityBySection([
      movement({ section_id: "A-B-UP", enter_min: 0 }),
      movement({ section_id: "C-D-UP", enter_min: 0 }),
      movement({ section_id: "C-D-UP", enter_min: 0 }),
    ]);
    expect(density.get("A-B-UP")![0]).toBe(1);
    expect(density.get("C-D-UP")![0]).toBe(2);
  });

  it("clamps a minute-of-day at the boundary into the last bucket rather than throwing", () => {
    const density = computeDensityBySection([movement({ enter_min: 1439 })]);
    const buckets = density.get("A-B-UP")!;
    expect(buckets[BUCKETS_PER_DAY - 1]).toBe(1);
  });

  it("returns an empty map for no movements", () => {
    expect(computeDensityBySection([]).size).toBe(0);
  });
});
