import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ComparisonTable, type ColumnDef } from "./ComparisonTable";

const fixed1 = (v: number | string) => Number(v).toFixed(1);
const fixed2 = (v: number | string) => Number(v).toFixed(2);

const METHOD_COLUMNS: ColumnDef[] = [
  { key: "method", label: "Method" },
  { key: "traffic_cost", label: "Traffic cost", numeric: true, format: fixed1 },
  { key: "mean_reliability", label: "Mean R", numeric: true, format: fixed2 },
  { key: "min_reliability", label: "Min R", numeric: true, format: fixed2 },
];

/** Values as they stand in the frozen method_comparison.csv. */
const ROWS = [
  { method: "B4 Bundle-only", traffic_cost: 272.8, mean_reliability: 0.99, min_reliability: 0.74 },
  { method: "OURS", traffic_cost: 299.2, mean_reliability: 0.99, min_reliability: 0.9 },
];

function renderTable() {
  const { container } = render(
    <ComparisonTable rows={ROWS} columns={METHOD_COLUMNS} highlightMethod="OURS" />
  );
  return container;
}

describe("ComparisonTable renders the full column set", () => {
  it("renders every column header, Min R included", () => {
    const container = renderTable();
    const heads = Array.from(container.querySelectorAll("thead th")).map((h) => h.textContent);
    expect(heads).toEqual(["Method", "Traffic cost", "Mean R", "Min R"]);
    expect(heads).toContain("Min R");
  });

  it("renders a Min R cell for every row, with the frozen values", () => {
    const container = renderTable();
    const rows = Array.from(container.querySelectorAll("tbody tr"));
    const minR = rows.map((r) => r.querySelectorAll("td")[3].textContent);
    expect(minR).toEqual(["0.74", "0.90"]);
  });

  it("keeps numeric cells right-aligned and tabular", () => {
    const container = renderTable();
    const cells = Array.from(container.querySelectorAll("tbody tr")[0].querySelectorAll("td"));
    expect(cells[0].className).not.toContain("comparison-table__num");
    for (const c of cells.slice(1)) {
      expect(c.className).toContain("comparison-table__num");
    }
  });

  it("passes values straight through without inventing precision", () => {
    const container = renderTable();
    const first = Array.from(container.querySelectorAll("tbody tr")[0].querySelectorAll("td"));
    expect(first.map((c) => c.textContent)).toEqual(["B4 Bundle-only", "272.8", "0.99", "0.74"]);
  });

  it("still highlights the OURS row", () => {
    const container = renderTable();
    const highlighted = container.querySelectorAll(".comparison-table__row--highlight");
    expect(highlighted).toHaveLength(1);
    expect(highlighted[0].textContent).toContain("OURS");
  });

  it("keeps the table inside a scroll container so nothing is silently lost", () => {
    const container = renderTable();
    expect(container.querySelector(".comparison-table__scroll")).not.toBeNull();
  });
});
