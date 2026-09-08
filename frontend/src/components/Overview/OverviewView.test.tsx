import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OverviewView } from "./OverviewView";
import type { CorridorResponse, PlanResponse } from "../../api/types";

const CORRIDOR: CorridorResponse = {
  stations: [
    { station_code: "JTJ", station_name: "Jolarpettai", latitude: 12.5, longitude: 78.5, seq: 1, is_junction: true },
    { station_code: "TPT", station_name: "Tirupattur", latitude: 12.4, longitude: 78.6, seq: 2, is_junction: false },
    { station_code: "SA", station_name: "Salem", latitude: 11.6, longitude: 78.1, seq: 3, is_junction: true },
  ],
  sections: [
    { section_id: "JTJ-TPT-UP", from_station_code: "JTJ", to_station_code: "TPT", line: "UP", length_km: 20.5, tracks: 2, electrified: true, is_single: false, headway_min: 4 },
    { section_id: "JTJ-TPT-DN", from_station_code: "JTJ", to_station_code: "TPT", line: "DN", length_km: 20.5, tracks: 2, electrified: true, is_single: false, headway_min: 4 },
    { section_id: "TPT-SA-UP", from_station_code: "TPT", to_station_code: "SA", line: "UP", length_km: 30.5, tracks: 2, electrified: true, is_single: false, headway_min: 8 },
  ],
};

const PLAN = {
  plan_id: "2db53586d84f",
  scenario: "NORMAL_TRAFFIC",
  horizon_days: 14,
  theta: 0.9,
  status: "OPTIMAL",
  cache_hit: false,
  objective: 337.4,
  blocks: [],
  deferred: [],
  summary: {
    blocks: 140,
    jobs_done: 174,
    jobs_deferred: 1,
    traffic_cost: 299.2,
    traffic_per_job: 1.7,
    exp_overrun_cost: 38.6,
    cross_dept_blocks: 51,
    cross_dept_share: 0.364,
    min_reliability: 0.9,
    mean_reliability: 0.99,
    block_utilisation: 0.385,
  },
  availability: {
    availability: 0.97791,
    occupied_share: 0.02209,
    capacity_minutes: 1048320,
    block_minutes: 23160,
    block_hours: 386,
    blocks: 140,
    section_lines: 52,
    horizon_days: 14,
    jobs_done: 174,
    jobs_deferred: 1,
    traffic_delay_minutes: 299.2,
    delay_per_weighted_movement: 0.004078,
    weighted_movements: 73376.8,
    headline: "97.8% corridor availability while completing 174 of 175 jobs",
    by_section: [],
  },
  stage_timings_s: { total: 12.3 },
  instance: {
    base_jobs: 175,
    jobs_after_pairing: 238,
    bundles: 449,
    windows: 11648,
    columns: 16746,
    mc_samples: 1500,
    max_bundle_size: 5,
    seed: null,
  },
} as PlanResponse;

function renderView(overrides: Partial<Parameters<typeof OverviewView>[0]> = {}) {
  const onOpenPlan = vi.fn();
  const utils = render(
    <OverviewView
      corridor={CORRIDOR}
      plan={PLAN}
      isPlanning={false}
      scenario="NORMAL_TRAFFIC"
      onOpenPlan={onOpenPlan}
      {...overrides}
    />
  );
  return { ...utils, onOpenPlan };
}

describe("OverviewView", () => {
  it("counts the corridor from the response, not from a constant", () => {
    renderView();
    expect(screen.getByText(/3 stations/)).toBeInTheDocument();
    expect(screen.getByText(/3 section-lines/)).toBeInTheDocument();
  });

  it("sums corridor length over one direction only", () => {
    // Both directions carry the same kilometres; adding UP and DN would report
    // a corridor twice as long as it is.
    renderView();
    expect(screen.getByText("51.0")).toBeInTheDocument();
  });

  it("pairs the availability figure with the work it bought", () => {
    const { container } = renderView();
    const panel = container.querySelector(".overview__availability");
    expect(panel).toHaveTextContent("97.8");
    expect(panel).toHaveTextContent(/174 of 175/);
    expect(panel).toHaveTextContent(/386.0 section-hours/);
    expect(panel).toHaveTextContent(/299.2 weighted/);
  });

  it("says no plan has been computed rather than showing zeros", () => {
    renderView({ plan: null });
    expect(screen.getByText(/No plan computed yet/)).toBeInTheDocument();
    // A zero block count is a real and different statement.
    expect(screen.queryByText("140")).toBeNull();
  });

  it("marks minimum reliability against the applied theta", () => {
    const { container } = renderView();
    const card = screen.getByText("0.90").closest("[data-testid='kpi-card']");
    expect(card).toHaveTextContent(/θ = 0.90/);
    expect(container.querySelector(".kpi--positive")).not.toBeNull();
  });

  it("links through to the block plan", () => {
    // fireEvent, matching the idiom the rest of this suite already uses --
    // @testing-library/user-event is not a dependency of this project and one
    // click is not a reason to add one.
    const { onOpenPlan } = renderView();
    fireEvent.click(screen.getByRole("button", { name: /Open block plan/ }));
    expect(onOpenPlan).toHaveBeenCalledOnce();
  });
});
