import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { JobExplanation } from "../../api/types";
import { JobExplanationView } from "./JobExplanationView";

function outbidExplanation(overrides: Partial<JobExplanation> = {}): JobExplanation {
  return {
    plan_id: "p1",
    job_id: "J00059",
    scenario: "URGENT_MAINTENANCE",
    decision_status: "DEFERRED",
    verdict: "OUTBID",
    applied_theta: 0.9,
    job: {
      job_id: "J00059",
      dept: "ENGG",
      activity: "TRACK_GEOMETRY_CORRECTION",
      section_id: "BDY-BQI-UP",
      km_from: 1.0,
      km_to: 2.0,
      duration_mean_min: 45,
      duration_sd_min: 15,
      due_day: 0,
      criticality: 0.9,
      protection_required: ["T"],
      resources: [],
      is_companion: false,
      parent_id: null,
      needs_train_movements: false,
      needs_live_ohe: false,
      provenance: "D_SYNTHETIC",
    },
    detail: "Admissible placements exist, but inserting this job would raise the plan objective by 7.1 weighted train-minutes.",
    candidate_columns: 12,
    price_of_forcing: 7.1,
    would_go_in: {
      day: 9, start: 300, length: 240, with: [], reliability: 0.95, traffic_cost: 0.0,
    },
    displaced: ["J00002", "J00004"],
    newly_displaced: ["J00004"],
    evidence: [
      { code: "PRICED_FORCED_INSERTION", statement: "…", source: "core.explain_refusal", provenance: "E_ASSUMPTION" },
    ],
    computation: {},
    ...overrides,
  };
}

describe("JobExplanationView OUTBID rendering", () => {
  /**
   * Regression test: found during browser verification of J00059 that
   * `would_go_in` (the hypothetical placement -- day, time, length,
   * reliability) was returned by the backend but silently never rendered.
   * Only `newly_displaced` was shown. This test fails if that field is
   * dropped again.
   */
  it("renders would_go_in's day, time, length and reliability", () => {
    render(<JobExplanationView explanation={outbidExplanation()} onSelectBlock={vi.fn()} />);

    expect(screen.getByText(/would go in/i)).toBeInTheDocument();
    expect(screen.getByText(/day 9/i)).toBeInTheDocument();
    expect(screen.getByText(/05:00/)).toBeInTheDocument(); // 300 min = 05:00
    expect(screen.getByText(/240 min/)).toBeInTheDocument();
    expect(screen.getByText(/0\.95/)).toBeInTheDocument();
  });

  it("also renders newly_displaced (the honest subset, not the raw displaced list)", () => {
    render(<JobExplanationView explanation={outbidExplanation()} onSelectBlock={vi.fn()} />);

    expect(screen.getByText(/would push out/i)).toBeInTheDocument();
    expect(screen.getByText(/J00004/)).toBeInTheDocument();
    // The full `displaced` list (J00002 included) must NOT leak into the
    // rendered text -- that field intentionally includes jobs already
    // deferred in the baseline, which `newly_displaced` excludes.
    expect(screen.queryByText(/J00002/)).not.toBeInTheDocument();
  });

  it("renders price_of_forcing and candidate_columns", () => {
    const { container } = render(
      <JobExplanationView explanation={outbidExplanation()} onSelectBlock={vi.fn()} />
    );
    const stats = container.querySelector(".job-why__outbid-stats");
    expect(stats).not.toBeNull();
    expect(stats!.textContent).toMatch(/7\.1/);
    expect(stats!.textContent).toMatch(/12/);
  });

  it("omits the would-go-in line entirely when the backend sends none", () => {
    render(
      <JobExplanationView
        explanation={outbidExplanation({ would_go_in: null })}
        onSelectBlock={vi.fn()}
      />
    );
    expect(screen.queryByText(/would go in/i)).not.toBeInTheDocument();
  });
});
