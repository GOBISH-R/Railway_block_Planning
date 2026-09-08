import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";
import { NAV_ITEMS, type ViewKey } from "./navigation";

/**
 * The shell went to eight destinations and back to three. The risk in either
 * direction is the same: a view becomes unreachable, or two share a key and
 * one silently shadows the other. Neither shows up as a visual defect, so it
 * is asserted here rather than left to inspection.
 *
 * The count is pinned deliberately. Each time tabs were cut, `App.tsx` kept
 * rendering branches for keys that no longer existed in `ViewKey` -- a failing
 * count is the cheapest signal that the two files have drifted apart again.
 */
describe("AppShell", () => {
  it("exposes every destination", () => {
    render(
      <AppShell active="overview" onNavigate={vi.fn()}>
        <div />
      </AppShell>
    );
    for (const item of NAV_ITEMS) {
      expect(screen.getByRole("button", { name: item.label })).toBeInTheDocument();
    }
    expect(NAV_ITEMS).toHaveLength(3);
  });

  it("gives every destination a unique key and label", () => {
    const keys = NAV_ITEMS.map((i) => i.key);
    const labels = NAV_ITEMS.map((i) => i.label);
    expect(new Set(keys).size).toBe(keys.length);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("keeps Corridor & Demand reachable", () => {
    // It predates the redesign and was explicitly to be preserved, not folded
    // into another view.
    expect(NAV_ITEMS.map((i) => i.key)).toContain("corridor");
    render(
      <AppShell active="overview" onNavigate={vi.fn()}>
        <div />
      </AppShell>
    );
    expect(screen.getByRole("button", { name: "Corridor & Demand" })).toBeInTheDocument();
  });

  it("marks exactly one destination as current", () => {
    render(
      <AppShell active="corridor" onNavigate={vi.fn()}>
        <div />
      </AppShell>
    );
    const current = screen
      .getAllByRole("button")
      .filter((b) => b.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Corridor & Demand");
  });

  it("navigates to the destination that was clicked", () => {
    const onNavigate = vi.fn();
    render(
      <AppShell active="overview" onNavigate={onNavigate}>
        <div />
      </AppShell>
    );
    fireEvent.click(screen.getByRole("button", { name: "Block Plan" }));
    expect(onNavigate).toHaveBeenCalledWith("timeline" satisfies ViewKey);
  });

  it("renders whatever the active view supplies", () => {
    render(
      <AppShell active="overview" onNavigate={vi.fn()}>
        <p>view content</p>
      </AppShell>
    );
    expect(screen.getByText("view content")).toBeInTheDocument();
  });
});
