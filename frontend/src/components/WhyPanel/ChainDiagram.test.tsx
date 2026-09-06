import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DepartmentalChain } from "../../api/types";
import { ChainDiagram } from "./ChainDiagram";

function chain(dept: string, mean_min: number, sd_min: number, phi: number): DepartmentalChain {
  return { dept, mean_min, sd_min, phi } as DepartmentalChain;
}

/** The three chains of a typical multi-department block. */
const CHAINS = [chain("ENGG", 118, 22, 0.97), chain("SNT", 74, 15, 0.99), chain("TRD", 91, 18, 0.98)];

const VIEWBOX_WIDTH = 360;

function renderDiagram(blockLength: number, chains = CHAINS) {
  const { container } = render(<ChainDiagram chains={chains} blockLength={blockLength} />);
  const svg = container.querySelector("svg")!;
  return { svg, container };
}

describe("ChainDiagram geometry", () => {
  /**
   * Regression: the envelope label is centred on its line, and when the block
   * filled the scale the right half ran past the viewBox edge -- rendering
   * "150 min envelop" with the last letter clipped away. The label is now
   * clamped to stay inside the box.
   */
  it("keeps the envelope label inside the viewBox when the block fills the scale", () => {
    // A block longer than every chain's mean + 2sd puts the envelope at the
    // far right of the scale, which is the case that used to clip.
    const { svg } = renderDiagram(400);
    const label = svg.querySelector<SVGTextElement>(".chain-diagram__envelope-label")!;

    expect(label.textContent).toBe("400 min envelope");

    const cx = Number(label.getAttribute("x"));
    const half = (label.textContent!.length * 4.6) / 2;
    expect(cx - half).toBeGreaterThanOrEqual(0);
    expect(cx + half).toBeLessThanOrEqual(VIEWBOX_WIDTH);
  });

  it("keeps the envelope label inside the viewBox when the block is a small fraction of the scale", () => {
    // The mirror case: one very long chain pushes the envelope hard left.
    const { svg } = renderDiagram(20, [chain("ENGG", 300, 40, 0.9), ...CHAINS]);
    const label = svg.querySelector<SVGTextElement>(".chain-diagram__envelope-label")!;

    const cx = Number(label.getAttribute("x"));
    const half = (label.textContent!.length * 4.6) / 2;
    expect(cx - half).toBeGreaterThanOrEqual(0);
    expect(cx + half).toBeLessThanOrEqual(VIEWBOX_WIDTH);
  });

  /**
   * Regression: the phi labels are right-anchored at the viewBox edge, and the
   * plot used to run the full width, so a long block put the dashed envelope
   * line straight through them.
   */
  it("keeps the envelope line clear of the right-hand phi labels", () => {
    const { svg } = renderDiagram(400);
    const line = svg.querySelector<SVGLineElement>(".chain-diagram__envelope")!;
    const phi = svg.querySelector<SVGTextElement>(".chain-diagram__phi-label")!;

    const lineX = Number(line.getAttribute("x1"));
    // Phi labels are anchored end-on at width - 4; "Phi=0.00" at 9px mono is
    // roughly 46px wide, so this is where their left edge falls.
    const phiLeftEdge = Number(phi.getAttribute("x")) - 46;

    expect(lineX).toBeLessThan(phiLeftEdge);
  });

  /**
   * Regression: `scale()` fed the envelope line directly while bars and mean
   * ticks added +30 for the department-label gutter, so the line sat 30 units
   * left of the data it is compared against -- chains looked like they crossed
   * the envelope when they did not. Both now go through one `x()`.
   */
  it("draws the envelope line and the chain bars in the same coordinate frame", () => {
    // Block length equal to a chain's mean: the mean tick must land exactly on
    // the envelope line. Under the old two-frame geometry it was 30 units off.
    const { svg } = renderDiagram(118);
    const line = svg.querySelector<SVGLineElement>(".chain-diagram__envelope")!;
    const engMeanTick = svg.querySelector<SVGLineElement>(".chain-diagram__mean-tick")!;

    expect(Number(engMeanTick.getAttribute("x1"))).toBeCloseTo(Number(line.getAttribute("x1")), 6);
  });

  it("still marks the longest chain as the binding one", () => {
    const { svg } = renderDiagram(150);
    // ENGG has the largest mean, so it is drawn at full opacity and the rest muted.
    const bars = Array.from(svg.querySelectorAll("rect"));
    expect(bars).toHaveLength(3);
    expect(bars[0].getAttribute("opacity")).toBe("1");
    expect(bars[1].getAttribute("opacity")).toBe("0.55");
    expect(svg.getAttribute("aria-label")).toContain("ENGG has the longest chain at 118 minutes");
  });
});
