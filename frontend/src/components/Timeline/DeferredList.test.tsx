import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DeferredEntry } from "../../api/types";
import { DeferredList } from "./DeferredList";

const SOME_DEFERRED: DeferredEntry[] = [
  { job_id: "J00086", dept: "ENGG" },
  { job_id: "J00012", dept: "SNT" },
  { job_id: "J00044", dept: "TRD" },
];

function renderList(deferred: DeferredEntry[], onSelectJob = vi.fn()) {
  const { container } = render(<DeferredList deferred={deferred} onSelectJob={onSelectJob} />);
  return { container, onSelectJob };
}

describe("DeferredList with zero deferred jobs", () => {
  it("states plainly that nothing was deferred", () => {
    renderList([]);
    expect(screen.getByText("No jobs deferred")).toBeInTheDocument();
    expect(
      screen.getByText(/All maintenance demand is scheduled within the current planning constraints\./)
    ).toBeInTheDocument();
  });

  /**
   * The empty state used to drop the panel heading entirely, leaving a bare
   * sentence beside the timeline that read as an unfinished column rather
   * than as this panel reporting zero.
   */
  it("keeps the panel heading, so an empty result still reads as a panel", () => {
    const { container } = renderList([]);
    const title = container.querySelector(".deferred-list__title");
    expect(title).not.toBeNull();
    expect(title!.textContent).toBe("Deferred (0)");
  });

  it("renders no job rows and nothing clickable", () => {
    const { container } = renderList([]);
    expect(container.querySelectorAll(".deferred-list__item")).toHaveLength(0);
    expect(container.querySelectorAll("button")).toHaveLength(0);
  });

  it("does not invent counts, reasons or job identifiers", () => {
    const { container } = renderList([]);
    const text = container.textContent!;
    // The only digit permitted is the zero in the heading.
    expect(text.replace("Deferred (0)", "")).not.toMatch(/\d/);
    expect(text).not.toMatch(/J\d{5}/);
    expect(text).not.toMatch(/reliability|theta|θ|because|reason/i);
  });

  it("keeps the panel's own layout class rather than a separate empty container", () => {
    const { container } = renderList([]);
    expect(container.querySelector(".deferred-list")).not.toBeNull();
    expect(container.querySelector(".deferred-list--empty")).toBeNull();
  });
});

describe("DeferredList with deferred jobs present", () => {
  it("shows the count in the heading and one row per job", () => {
    const { container } = renderList(SOME_DEFERRED);
    expect(container.querySelector(".deferred-list__title")!.textContent).toContain("Deferred (3)");
    expect(container.querySelectorAll(".deferred-list__item")).toHaveLength(3);
  });

  it("lists every job id, in order", () => {
    const { container } = renderList(SOME_DEFERRED);
    const ids = Array.from(container.querySelectorAll(".deferred-list__job-id")).map(
      (n) => n.textContent
    );
    expect(ids).toEqual(["J00086", "J00012", "J00044"]);
  });

  it("keeps the click-to-explain affordance and hands back the job id", () => {
    const { container, onSelectJob } = renderList(SOME_DEFERRED);
    expect(container.textContent).toContain("Click a job to see why");
    fireEvent.click(container.querySelectorAll(".deferred-list__item")[1]);
    expect(onSelectJob).toHaveBeenCalledWith("J00012");
  });

  it("never shows the empty-state wording when jobs are deferred", () => {
    renderList(SOME_DEFERRED);
    expect(screen.queryByText("No jobs deferred")).not.toBeInTheDocument();
    expect(screen.queryByText(/All maintenance demand is scheduled/)).not.toBeInTheDocument();
  });

  it("still renders a single deferred job as a list, not as an empty state", () => {
    const { container } = renderList([{ job_id: "J00086", dept: "ENGG" }]);
    expect(container.querySelector(".deferred-list__title")!.textContent).toContain("Deferred (1)");
    expect(container.querySelectorAll(".deferred-list__item")).toHaveLength(1);
    expect(screen.queryByText("No jobs deferred")).not.toBeInTheDocument();
  });
});
