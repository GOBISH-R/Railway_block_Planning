import { describe, expect, it } from "vitest";
import { scenarioLabel } from "./scenarioLabel";

/** Every scenario the backend serves, exactly as it appears on the wire. */
const SCENARIOS = [
  "NORMAL_TRAFFIC",
  "PEAK_TRAFFIC",
  "HEAVY_FREIGHT",
  "MAINTENANCE_BACKLOG",
  "URGENT_MAINTENANCE",
  "HIGH_DURATION_UNCERTAINTY",
  "DISRUPTED_OPERATION",
  "MULTIPLE_DEPARTMENT_REQUESTS",
] as const;

describe("scenarioLabel", () => {
  it("renders the case from the reported defect", () => {
    expect(scenarioLabel("NORMAL_TRAFFIC")).toBe("Normal Traffic");
  });

  it("labels all eight supported scenarios by the same convention", () => {
    expect(SCENARIOS.map(scenarioLabel)).toEqual([
      "Normal Traffic",
      "Peak Traffic",
      "Heavy Freight",
      "Maintenance Backlog",
      "Urgent Maintenance",
      "High Duration Uncertainty",
      "Disrupted Operation",
      "Multiple Department Requests",
    ]);
  });

  it("leaves no underscores or shouted words in any label", () => {
    for (const name of SCENARIOS) {
      const label = scenarioLabel(name);
      expect(label).not.toContain("_");
      expect(label).not.toBe(name);
      for (const word of label.split(" ")) {
        expect(word[0]).toBe(word[0].toUpperCase());
        expect(word.slice(1)).toBe(word.slice(1).toLowerCase());
      }
    }
  });

  it("is display-only: the label maps back to nothing the API ever sees", () => {
    // The wire value is what callers must keep passing; this guards against
    // anyone "simplifying" by feeding the label back in as the value.
    expect(scenarioLabel("NORMAL_TRAFFIC")).not.toBe("NORMAL_TRAFFIC");
    expect(SCENARIOS.map(scenarioLabel)).not.toContain("NORMAL_TRAFFIC");
  });

  it("survives stray underscores rather than throwing on an empty segment", () => {
    expect(scenarioLabel("_LEADING")).toBe("Leading");
    expect(scenarioLabel("TRAILING_")).toBe("Trailing");
    expect(scenarioLabel("DOUBLE__UNDERSCORE")).toBe("Double Underscore");
  });

  it("returns the input unchanged when there is nothing to format", () => {
    expect(scenarioLabel("")).toBe("");
    expect(scenarioLabel("_")).toBe("_");
  });
});
