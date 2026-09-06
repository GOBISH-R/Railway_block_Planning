import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ScenarioRow } from "../../api/types";
import { ControlsBar } from "./ControlsBar";

function scenarioRow(name: string): ScenarioRow {
  return {
    name,
    demand_scale: 1, freight_scale: 1, uncertainty_scale: 1, urgency_shift: 0,
    backlog: 0, extra_passenger_scale: null, cancel_window_fraction: null,
    note: `${name} note`, realised_job_count: 175,
  };
}

const SCENARIOS = ["NORMAL_TRAFFIC", "PEAK_TRAFFIC", "MULTIPLE_DEPARTMENT_REQUESTS"].map(scenarioRow);

function renderBar(onScenarioChange = vi.fn()) {
  const { container } = render(
    <ControlsBar
      scenarios={SCENARIOS}
      scenario="NORMAL_TRAFFIC"
      onScenarioChange={onScenarioChange}
      theta={0.9}
      onThetaChange={vi.fn()}
      horizonDays={14}
      onHorizonChange={vi.fn()}
      onReplan={vi.fn()}
      isPlanning={false}
    />
  );
  const select = screen.getByLabelText("Scenario") as HTMLSelectElement;
  return { container, select, onScenarioChange };
}

describe("ControlsBar scenario dropdown", () => {
  it("shows human-readable labels", () => {
    const { select } = renderBar();
    expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
      "Normal Traffic",
      "Peak Traffic",
      "Multiple Department Requests",
    ]);
  });

  /**
   * The label is presentation only. The option's value -- what reaches
   * onScenarioChange and then the API's `scenario` parameter -- must stay the
   * raw enum, or every request and every frozen-artefact lookup breaks.
   */
  it("keeps the raw enum as each option's value", () => {
    const { select } = renderBar();
    expect(Array.from(select.options).map((o) => o.value)).toEqual([
      "NORMAL_TRAFFIC",
      "PEAK_TRAFFIC",
      "MULTIPLE_DEPARTMENT_REQUESTS",
    ]);
    expect(select.value).toBe("NORMAL_TRAFFIC");
  });

  it("hands the raw enum, not the label, to onScenarioChange", () => {
    const { select, onScenarioChange } = renderBar();
    fireEvent.change(select, { target: { value: "PEAK_TRAFFIC" } });
    expect(onScenarioChange).toHaveBeenCalledWith("PEAK_TRAFFIC");
    expect(onScenarioChange).not.toHaveBeenCalledWith("Peak Traffic");
  });
});
