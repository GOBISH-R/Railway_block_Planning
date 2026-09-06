import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CorridorResponse, PlanResponse } from "../../api/types";

const traffic = vi.fn();
vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return { ...actual, api: { ...actual.api, traffic: (s: string) => traffic(s) } };
});

const { TimelineView } = await import("./TimelineView");

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

function planWith(deferred: PlanResponse["deferred"]): PlanResponse {
  return {
    plan_id: "p1", scenario: "NORMAL_TRAFFIC", status: "OPTIMAL", theta: 0.9,
    horizon_days: 14, objective: 337.4, cache_hit: false,
    blocks: [], deferred,
    summary: {
      blocks: 0, jobs_done: 175, jobs_deferred: deferred.length, traffic_cost: 299.2,
      traffic_per_job: 1.7, exp_overrun_cost: 60, cross_dept_blocks: 0, cross_dept_share: 0,
      min_reliability: 0.9, mean_reliability: 0.99, block_utilisation: 0.4,
    },
    instance: {}, stage_timings_s: {},
  } as unknown as PlanResponse;
}

function renderView(overrides: Partial<Parameters<typeof TimelineView>[0]> = {}) {
  return render(
    <TimelineView
      corridor={CORRIDOR}
      scenarios={[]}
      scenario="NORMAL_TRAFFIC"
      onScenarioChange={vi.fn()}
      theta={0.9}
      onThetaChange={vi.fn()}
      horizonDays={14}
      onHorizonChange={vi.fn()}
      plan={null}
      isPlanning={false}
      onReplan={vi.fn()}
      onSelectBlock={vi.fn()}
      onSelectJob={vi.fn()}
      selectedBlockId={null}
      {...overrides}
    />
  );
}

/**
 * The empty state must mean "the optimiser deferred nothing", never "the data
 * has not arrived". That distinction is enforced structurally: TimelineView
 * renders DeferredList only under `{plan && ...}`, so `plan.deferred` cannot
 * be read before a plan exists. These tests pin that boundary, because a
 * future change that hoisted DeferredList out of the guard would start
 * claiming "No jobs deferred" against a plan that had not been computed.
 */
describe("DeferredList empty state is not shown for loading or missing data", () => {
  beforeEach(() => {
    traffic.mockReset();
    traffic.mockResolvedValue({ scenario: "NORMAL_TRAFFIC", movements: [] });
  });

  it("shows the loading state, not 'No jobs deferred', while the first plan is building", () => {
    renderView({ plan: null, isPlanning: true });
    expect(screen.getByText(/Building the initial plan/)).toBeInTheDocument();
    expect(screen.queryByText("No jobs deferred")).not.toBeInTheDocument();
    expect(screen.queryByText(/All maintenance demand is scheduled/)).not.toBeInTheDocument();
  });

  it("shows the no-plan state, not 'No jobs deferred', when there is no plan", () => {
    renderView({ plan: null, isPlanning: false });
    expect(screen.getByText("No plan yet")).toBeInTheDocument();
    expect(screen.queryByText("No jobs deferred")).not.toBeInTheDocument();
  });

  it("shows the empty state only once a real plan reports zero deferred", () => {
    renderView({ plan: planWith([]), isPlanning: false });
    expect(screen.getByText("No jobs deferred")).toBeInTheDocument();
    expect(screen.getByText(/All maintenance demand is scheduled/)).toBeInTheDocument();
  });

  it("shows the list, not the empty state, when a plan reports deferrals", () => {
    renderView({ plan: planWith([{ job_id: "J00086", dept: "ENGG" }]), isPlanning: false });
    expect(screen.getByText("J00086")).toBeInTheDocument();
    expect(screen.queryByText("No jobs deferred")).not.toBeInTheDocument();
  });

  it("hides the stale plan behind the re-planning veil rather than presenting it as current", () => {
    const { container } = renderView({ plan: planWith([]), isPlanning: true });
    expect(screen.getByText(/Re-planning/)).toBeInTheDocument();
    expect(container.querySelector(".timeline-view__content")!.getAttribute("aria-hidden")).toBe("true");
  });
});
