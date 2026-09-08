export type ViewKey = "overview" | "timeline" | "corridor";

export interface NavItem {
  key: ViewKey;
  label: string;
  hint: string;
}

/**
 * Three destinations: the operational product.
 *
 * An earlier revision carried eight, split across three groups -- separate
 * tabs for availability, data sources, the ML architecture, the running
 * configuration, and a benchmark comparison against five baselines. Most of
 * that was a page per fact, and none of it was the thing a block planner
 * actually opens. Availability now lives on the overview, beside the work it
 * bought.
 *
 * The benchmark itself is not gone -- it is still the frozen
 * `method_comparison.csv`, still served by `GET /comparison`, and still what
 * the written evidence quotes. It simply is not a screen in the planning app.
 */
export const NAV_ITEMS: NavItem[] = [
  { key: "overview", label: "Overview", hint: "The corridor and the current plan at a glance" },
  { key: "timeline", label: "Block Plan", hint: "The recommended blocks for the selected scenario" },
  { key: "corridor", label: "Corridor & Demand", hint: "The line, and what work is waiting on it" },
];
