import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CorridorStrip } from "./CorridorStrip";
import type { StationPoint } from "./corridorProfile";
import { STATION_LABEL_BASELINE_DY, stationLabelRow } from "./corridorProfile";

/**
 * The real JTJ-ED corridor: all 27 stations, their true cumulative km, and the
 * four junctions. Taken from GET /corridor so these tests constrain the layout
 * against the spacing it actually has to survive, not a convenient fixture.
 */
const REAL_STATIONS: Array<[string, number, boolean]> = [
  ["JTJ", 0.0, false], ["TPT", 7.5, true], ["MOLK", 11.7, false], ["KEY", 18.9, false],
  ["KNNT", 25.0, false], ["SLY", 30.9, false], ["DST", 39.5, false], ["DPI", 47.7, false],
  ["MAP", 55.1, false], ["TNGR", 61.3, false], ["BDY", 68.0, false], ["BQI", 78.2, false],
  ["LCR", 88.7, false], ["DSPT", 97.6, false], ["TNT", 104.5, false], ["KPPR", 114.7, false],
  ["MGSJ", 118.0, true], ["SA", 121.4, true], ["NEA", 128.5, false], ["VRPD", 131.5, false],
  ["DVBH", 136.1, false], ["DC", 142.7, false], ["MVPM", 155.5, false], ["SGE", 160.7, false],
  ["ANU", 168.7, false], ["CV", 177.2, false], ["ED", 182.001, true],
];

const STATIONS: StationPoint[] = REAL_STATIONS.map(([code, km, isJunction]) => ({
  station_code: code,
  station_name: code,
  km,
  is_junction: isJunction,
  latitude: 0,
  longitude: 0,
}));

/**
 * Estimated label width in viewBox units at the 14px label size.
 *
 * jsdom does no SVG text layout, so getBBox() is unavailable here. Fitted
 * instead to widths measured in a real browser, where the widest code of each
 * length was 12.3 / 20.0 / 27.66 units at 9px for 2 / 3 / 4 characters. That
 * is ~7.7 units per character less ~3 of side bearing, scaled by 14/9 and
 * rounded up: every real code comes out narrower than this, so the assertions
 * below are stricter than what the browser actually renders.
 */
function estimatedLabelWidth(code: string): number {
  return 12 * code.length - 4;
}

function renderStrip() {
  const { container } = render(
    <CorridorStrip stations={STATIONS} jobs={[]} filterDept={null} />
  );
  return container;
}

function labels(container: HTMLElement) {
  return Array.from(container.querySelectorAll(".corridor-strip__station-label")).map((t) => {
    const code = t.textContent!;
    const cx = Number(t.getAttribute("x"));
    const width = estimatedLabelWidth(code);
    return { code, cx, y: Number(t.getAttribute("y")), x0: cx - width / 2, x1: cx + width / 2 };
  });
}

describe("CorridorStrip station labels", () => {
  it("keeps all 27 real stations, in true corridor order", () => {
    const found = labels(renderStrip()).map((l) => l.code);
    expect(found).toHaveLength(27);
    expect(found).toEqual(REAL_STATIONS.map(([code]) => code));
  });

  it("places labels left to right in km order", () => {
    const xs = labels(renderStrip()).map((l) => l.cx);
    for (let i = 0; i < xs.length - 1; i++) {
      expect(xs[i]).toBeLessThan(xs[i + 1]);
    }
  });

  /**
   * The defect this change exists to fix. Centred on one baseline, KPPR/MGSJ
   * and NEA/VRPD overlapped by 3.0 and 3.1 units -- measured in the browser at
   * every width from 832px to 1440px, since the overlap is in viewBox space
   * and therefore scale-independent.
   */
  it("never lets two labels on the same baseline overlap", () => {
    const placed = labels(renderStrip());
    const collisions: string[] = [];
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        if (placed[j].x0 >= placed[i].x1) break;
        if (placed[i].y === placed[j].y) {
          collisions.push(`${placed[i].code}|${placed[j].code}`);
        }
      }
    }
    expect(collisions).toEqual([]);
  });

  it("separates the two pairs that used to collide", () => {
    const byCode = new Map(labels(renderStrip()).map((l) => [l.code, l]));
    expect(byCode.get("KPPR")!.y).not.toBe(byCode.get("MGSJ")!.y);
    expect(byCode.get("NEA")!.y).not.toBe(byCode.get("VRPD")!.y);
  });

  it("uses exactly two baselines and puts adjacent stations on different ones", () => {
    const placed = labels(renderStrip());
    expect(new Set(placed.map((l) => l.y)).size).toBe(2);
    for (let i = 0; i < placed.length - 1; i++) {
      expect(placed[i].y).not.toBe(placed[i + 1].y);
    }
  });

  it("keeps the first and last labels inside the viewBox", () => {
    const placed = labels(renderStrip());
    const viewBoxWidth = Number(
      renderStrip().querySelector("svg")!.getAttribute("viewBox")!.split(/\s+/)[2]
    );
    expect(placed[0].x0).toBeGreaterThanOrEqual(0);
    expect(placed[placed.length - 1].x1).toBeLessThanOrEqual(viewBoxWidth);
  });

  it("leaves headroom for the font size rather than only just fitting", () => {
    // Same-baseline neighbours are stations i and i+2. The tightest real pair
    // (NEA -> DVBH) must keep clear space, so that raising the label size
    // cannot silently reintroduce the overlap this suite exists to prevent.
    // Against the deliberately pessimistic width model above this reads 1.25;
    // against widths actually measured in the browser it is 1.47.
    const placed = labels(renderStrip());
    let worst = Infinity;
    for (let i = 0; i + 2 < placed.length; i++) {
      const gap = placed[i + 2].cx - placed[i].cx;
      const required = (placed[i].x1 - placed[i].x0 + (placed[i + 2].x1 - placed[i + 2].x0)) / 2;
      worst = Math.min(worst, gap / required);
    }
    expect(worst).toBeGreaterThan(1.15);
  });
});

describe("CorridorStrip ticks and leaders", () => {
  it("gives every station its own tick at its true km position", () => {
    const container = renderStrip();
    const ticks = Array.from(container.querySelectorAll(".corridor-strip__tick"));
    expect(ticks).toHaveLength(27);

    // Ticks and labels share an x: a staggered label still points at its station.
    const tickXs = ticks.map((t) => Number(t.getAttribute("x1")));
    expect(tickXs).toEqual(labels(container).map((l) => l.cx));
  });

  it("marks the four real junctions with the heavier tick", () => {
    const container = renderStrip();
    expect(container.querySelectorAll(".corridor-strip__tick--junction")).toHaveLength(4);
  });

  it("draws a leader only for the lower row, joining the label to its tick", () => {
    const container = renderStrip();
    const leaders = Array.from(container.querySelectorAll(".corridor-strip__leader"));
    // 27 stations alternating from row 0 leaves 13 on the lower row.
    expect(leaders).toHaveLength(13);

    const lowerY = Math.max(...labels(container).map((l) => l.y));
    for (const leader of leaders) {
      expect(Number(leader.getAttribute("y2"))).toBeLessThan(lowerY);
      expect(Number(leader.getAttribute("y1"))).toBeLessThan(Number(leader.getAttribute("y2")));
    }
  });

  it("grows the viewBox to fit the second baseline", () => {
    const container = renderStrip();
    const [, , , height] = container.querySelector("svg")!.getAttribute("viewBox")!.split(/\s+/).map(Number);
    const lowestBaseline = Math.max(...labels(container).map((l) => l.y));
    expect(height).toBeGreaterThan(lowestBaseline);
  });
});

describe("CorridorStrip station guides", () => {
  it("drops a guide from every station to the corridor spine", () => {
    const container = renderStrip();
    const guides = Array.from(container.querySelectorAll(".corridor-strip__guide"));
    expect(guides).toHaveLength(27);
  });

  /**
   * The point of the guides: the job lanes and the corridor share one km axis,
   * and this is what makes that visible. A guide that did not line up with its
   * station's tick would be worse than none.
   */
  it("aligns each guide with its own station tick", () => {
    const container = renderStrip();
    const guideXs = Array.from(container.querySelectorAll(".corridor-strip__guide")).map((g) =>
      Number(g.getAttribute("x1"))
    );
    const tickXs = Array.from(container.querySelectorAll(".corridor-strip__tick")).map((t) =>
      Number(t.getAttribute("x1"))
    );
    expect(guideXs).toEqual(tickXs);
  });

  it("keeps each guide vertical and stops it at the spine", () => {
    const container = renderStrip();
    const spineY = Number(
      container.querySelector(".corridor-strip__line")!.getAttribute("y1")
    );
    for (const g of container.querySelectorAll(".corridor-strip__guide")) {
      expect(g.getAttribute("x1")).toBe(g.getAttribute("x2"));
      expect(Number(g.getAttribute("y1"))).toBe(0);
      expect(Number(g.getAttribute("y2"))).toBe(spineY);
    }
  });

  it("draws guides before the lane labels so text is never crossed by one", () => {
    const container = renderStrip();
    const svg = container.querySelector("svg")!;
    const children = Array.from(svg.children);
    const lastGuide = children.map((c) => c.classList.contains("corridor-strip__guide")).lastIndexOf(true);
    const firstLaneLabel = children.findIndex((c) =>
      c.classList.contains("corridor-strip__lane-label")
    );
    expect(lastGuide).toBeGreaterThanOrEqual(0);
    expect(firstLaneLabel).toBeGreaterThan(lastGuide);
  });

  it("leaves the station labels and ticks untouched", () => {
    const container = renderStrip();
    expect(container.querySelectorAll(".corridor-strip__station-label")).toHaveLength(27);
    expect(container.querySelectorAll(".corridor-strip__tick")).toHaveLength(27);
    expect(container.querySelectorAll(".corridor-strip__tick--junction")).toHaveLength(4);
  });
});

describe("stationLabelRow", () => {
  it("alternates so no two neighbours share a baseline", () => {
    expect(stationLabelRow(0)).toBe(0);
    expect(stationLabelRow(1)).toBe(1);
    expect(stationLabelRow(2)).toBe(0);
    expect(STATION_LABEL_BASELINE_DY).toHaveLength(2);
  });
});
