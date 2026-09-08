import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SummaryStrip } from "./SummaryStrip";
import type { PlanResponse } from "../../api/types";

const BASE = {
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

describe("SummaryStrip availability", () => {
  it("shows availability to two decimals", () => {
    // Whole percent would render five of the six benchmark methods as 97%.
    render(<SummaryStrip plan={BASE} />);
    expect(screen.getByText("97.79%")).toBeInTheDocument();
  });

  it("carries the work figures in the hover title, not just the percentage", () => {
    render(<SummaryStrip plan={BASE} />);
    const metric = screen.getByText("97.79%").closest(".summary-strip__metric");
    expect(metric).toHaveAttribute("title", expect.stringContaining("174 of 175"));
  });

  it("places availability after the work figures, not before them", () => {
    // Read left to right the row says what was done, then what it cost. The
    // percentage arriving first would invite reading it alone.
    const { container } = render(<SummaryStrip plan={BASE} />);
    const labels = Array.from(
      container.querySelectorAll(".summary-strip__label")
    ).map((n) => n.textContent);
    expect(labels.indexOf("Availability")).toBeGreaterThan(labels.indexOf("Jobs done"));
    expect(labels.indexOf("Availability")).toBeGreaterThan(labels.indexOf("Deferred"));
  });

  it("omits the metric entirely when the response carries no availability", () => {
    // Never 0%. A missing measurement rendered as zero is a fabricated one,
    // and the rest of the strip must still render.
    const withoutIt = { ...BASE } as Partial<PlanResponse>;
    delete withoutIt.availability;

    const { container } = render(<SummaryStrip plan={withoutIt as PlanResponse} />);
    expect(screen.queryByText(/Availability/)).toBeNull();
    expect(screen.queryByText("0.00%")).toBeNull();
    expect(container.querySelector(".summary-strip__metric")).not.toBeNull();
    expect(screen.getByText("140")).toBeInTheDocument();
  });
});
