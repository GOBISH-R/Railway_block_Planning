import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CorridorResponse, ScenarioRow } from "../../api/types";

const demand = vi.fn();
vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return { ...actual, api: { ...actual.api, demand: (s: string) => demand(s) } };
});

const { CorridorView } = await import("./CorridorView");

function scenarioRow(name: string): ScenarioRow {
  return {
    name,
    demand_scale: 1, freight_scale: 1, uncertainty_scale: 1, urgency_shift: 0,
    backlog: 0, extra_passenger_scale: null, cancel_window_fraction: null,
    note: "", realised_job_count: 175,
  };
}

const SCENARIOS = ["NORMAL_TRAFFIC", "HEAVY_FREIGHT", "HIGH_DURATION_UNCERTAINTY"].map(scenarioRow);

const CORRIDOR: CorridorResponse = {
  stations: [
    { station_code: "A", station_name: "A", latitude: 0, longitude: 0, seq: 0, is_junction: false },
    { station_code: "B", station_name: "B", latitude: 0, longitude: 0, seq: 1, is_junction: false },
  ],
  sections: [
    { section_id: "A-B-UP", from_station_code: "A", to_station_code: "B", line: "UP",
      length_km: 10, tracks: 2, electrified: true, is_single: false, headway_min: 5 },
  ],
};

describe("CorridorView scenario dropdown", () => {
  beforeEach(() => {
    demand.mockReset();
    demand.mockResolvedValue({ scenario: "NORMAL_TRAFFIC", jobs: [] });
  });

  async function renderView(onScenarioChange = vi.fn()) {
    render(
      <CorridorView
        corridor={CORRIDOR}
        scenarios={SCENARIOS}
        scenario="NORMAL_TRAFFIC"
        onScenarioChange={onScenarioChange}
      />
    );
    const select = screen.getByLabelText("Scenario") as HTMLSelectElement;
    await waitFor(() => expect(demand).toHaveBeenCalled());
    return select;
  }

  /**
   * The defect: this dropdown showed the raw enum while the Plan view's
   * showed "Normal Traffic", one navigation click apart.
   */
  it("shows the same human-readable labels the Plan view uses", async () => {
    const select = await renderView();
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      "Normal Traffic",
      "Heavy Freight",
      "High Duration Uncertainty",
    ]);
  });

  it("keeps the raw enum as each option's value", async () => {
    const select = await renderView();
    expect(Array.from(select.options).map((o) => o.value)).toEqual([
      "NORMAL_TRAFFIC",
      "HEAVY_FREIGHT",
      "HIGH_DURATION_UNCERTAINTY",
    ]);
    expect(select.value).toBe("NORMAL_TRAFFIC");
  });

  it("requests demand with the raw enum, not the display label", async () => {
    await renderView();
    expect(demand).toHaveBeenCalledWith("NORMAL_TRAFFIC");
  });
});
