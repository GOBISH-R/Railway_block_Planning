import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScatterPlot } from "./ScatterPlot";

/**
 * The six rows of the frozen method_comparison.csv, as EvidenceView derives
 * them. Values are quoted, never recomputed -- these tests must fail if the
 * plot ever stops showing one of them.
 */
const POINTS = [
  { method: "B0", traffic_cost: 391.4, min_reliability: 0.74 },
  { method: "B1", traffic_cost: 430.8, min_reliability: 0.9 },
  { method: "B2", traffic_cost: 743.4, min_reliability: 0.73 },
  { method: "B3", traffic_cost: 1750.2, min_reliability: 0.03 },
  { method: "B4", traffic_cost: 272.8, min_reliability: 0.74 },
  { method: "OURS", traffic_cost: 299.2, min_reliability: 0.9 },
];

function renderPlot(points = POINTS) {
  const { container } = render(<ScatterPlot points={points} />);
  const svg = container.querySelector("svg")!;
  const [, , vbWidth, vbHeight] = svg.getAttribute("viewBox")!.split(/\s+/).map(Number);
  return { container, svg, vbWidth, vbHeight };
}

function labels(svg: SVGElement) {
  return Array.from(svg.querySelectorAll(".scatter-plot__label")).map((t) => ({
    method: t.textContent!,
    x: Number(t.getAttribute("x")),
    y: Number(t.getAttribute("y")),
    anchor: t.getAttribute("text-anchor"),
  }));
}

function circles(svg: SVGElement) {
  return Array.from(svg.querySelectorAll(".scatter-plot__point")).map((c) => ({
    cx: Number(c.getAttribute("cx")),
    cy: Number(c.getAttribute("cy")),
    r: Number(c.getAttribute("r")),
  }));
}

describe("ScatterPlot keeps every benchmark point", () => {
  it("draws one point per method, none dropped or aggregated", () => {
    const { svg } = renderPlot();
    expect(circles(svg)).toHaveLength(POINTS.length);
    expect(labels(svg).map((l) => l.method).sort()).toEqual(
      ["B0", "B1", "B2", "B3", "B4", "OURS"]
    );
  });

  it("keeps B3, the outlier, plotted and labelled", () => {
    const { svg } = renderPlot();
    expect(labels(svg).map((l) => l.method)).toContain("B3");
  });

  it("plots every point inside the viewBox, so none is clipped at an edge", () => {
    const { svg, vbWidth, vbHeight } = renderPlot();
    for (const c of circles(svg)) {
      expect(c.cx - c.r).toBeGreaterThanOrEqual(0);
      expect(c.cx + c.r).toBeLessThanOrEqual(vbWidth);
      expect(c.cy - c.r).toBeGreaterThanOrEqual(0);
      expect(c.cy + c.r).toBeLessThanOrEqual(vbHeight);
    }
  });
});

describe("ScatterPlot shows B3 honestly as an outlier", () => {
  it("puts B3 far below every other method, not compressed towards them", () => {
    const { svg } = renderPlot();
    const ys = circles(svg).map((c) => c.cy).sort((a, b) => a - b);
    const lowest = ys[ys.length - 1];
    const nextLowest = ys[ys.length - 2];
    const clusterSpan = ys[ys.length - 2] - ys[0];
    // The gap from the cluster down to B3 dwarfs the cluster's own spread.
    expect(lowest - nextLowest).toBeGreaterThan(clusterSpan * 3);
  });

  it("anchors the reliability axis at a true zero rather than a negative domain", () => {
    const { svg } = renderPlot();
    const ticks = Array.from(svg.querySelectorAll(".scatter-plot__tick")).map((t) => t.textContent);
    // A 0.0 gridline gives B3 a labelled reference; it used to float below the
    // lowest line (0.2) with nothing to read it against.
    expect(ticks).toContain("0.0");
    expect(ticks).toContain("1.0");
  });

  it("keeps the reliability axis linear: equal reliability gaps map to equal pixels", () => {
    const { svg } = renderPlot([
      { method: "A", traffic_cost: 100, min_reliability: 0.2 },
      { method: "B", traffic_cost: 200, min_reliability: 0.5 },
      { method: "C", traffic_cost: 300, min_reliability: 0.8 },
    ]);
    const [a, b, c] = circles(svg);
    expect(a.cy - b.cy).toBeCloseTo(b.cy - c.cy, 6);
  });
});

describe("ScatterPlot label placement", () => {
  it("separates the OURS and B1 labels, which share a reliability exactly", () => {
    const { svg } = renderPlot();
    const placed = labels(svg);
    const ours = placed.find((l) => l.method === "OURS")!;
    const b1 = placed.find((l) => l.method === "B1")!;

    // Same row by construction -- both methods report min_reliability 0.90.
    expect(ours.y).toBeCloseTo(b1.y, 6);
    // So they must be separated horizontally, on opposite sides of their points.
    expect(ours.anchor).toBe("end");
    expect(b1.anchor).toBe("start");
    expect(b1.x).toBeGreaterThan(ours.x);
  });

  /**
   * The property that actually failed on screen: two labels sharing a row with
   * almost no space between them. Under the previous cost-rank stagger, "OURS"
   * ended 2.8px before "B1" began -- text reading as one run. Opposite sides
   * now put 51.9px between them.
   */
  it("leaves real space between labels that share a row", () => {
    const { svg } = renderPlot();
    const placed = labels(svg);
    const APPROX_CHAR_PX = 6.5;
    const MIN_GAP_PX = 12;

    const extent = (l: (typeof placed)[number]) => {
      const w = l.method.length * APPROX_CHAR_PX;
      const x0 = l.anchor === "end" ? l.x - w : l.x;
      return { x0, x1: x0 + w };
    };

    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        if (Math.abs(placed[i].y - placed[j].y) >= 9) continue;
        const a = extent(placed[i]);
        const b = extent(placed[j]);
        const gap = a.x0 < b.x0 ? b.x0 - a.x1 : a.x0 - b.x1;
        expect(gap).toBeGreaterThanOrEqual(MIN_GAP_PX);
      }
    }
  });

  it("keeps every label clear of every other method's marker", () => {
    const { svg } = renderPlot();
    const placed = labels(svg);
    const pts = circles(svg);
    const APPROX_CHAR_PX = 6.5; // 10px bold label, measured wider than reality

    for (const l of placed) {
      const width = l.method.length * APPROX_CHAR_PX;
      const x0 = l.anchor === "end" ? l.x - width : l.x;
      const x1 = x0 + width;
      for (const p of pts) {
        const sameRow = Math.abs(l.y - 3 - p.cy) < 6;
        const overlapsHorizontally = x0 < p.cx + p.r && x1 > p.cx - p.r;
        expect(sameRow && overlapsHorizontally).toBe(false);
      }
    }
  });

  it("labels every point exactly once, still attached to its own method", () => {
    const { svg } = renderPlot();
    const placed = labels(svg);
    expect(placed).toHaveLength(POINTS.length);
    expect(new Set(placed.map((l) => l.method)).size).toBe(POINTS.length);
  });
});
