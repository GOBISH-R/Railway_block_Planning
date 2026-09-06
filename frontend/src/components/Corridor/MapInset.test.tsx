import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MapInset } from "./MapInset";
import type { StationPoint } from "./corridorProfile";

/** A handful of the real corridor's stations, with their true coordinates. */
const STATIONS: StationPoint[] = [
  { station_code: "JTJ", station_name: "Jolarpettai", km: 0, is_junction: true, latitude: 12.5646, longitude: 78.5717 },
  { station_code: "TPT", station_name: "Tirupattur", km: 7.5, is_junction: true, latitude: 12.4959, longitude: 78.5686 },
  { station_code: "SA", station_name: "Salem", km: 121.4, is_junction: true, latitude: 11.6643, longitude: 78.1460 },
  { station_code: "ED", station_name: "Erode", km: 182.0, is_junction: true, latitude: 11.3410, longitude: 77.7172 },
];

function renderMap(stations = STATIONS) {
  const { container } = render(<MapInset stations={stations} />);
  const svg = container.querySelector("svg")!;
  const [, , width, height] = svg.getAttribute("viewBox")!.split(/\s+/).map(Number);
  return { container, svg, width, height };
}

describe("MapInset", () => {
  it("draws one route polyline through every station, in order", () => {
    const { svg } = renderMap();
    const pts = svg.querySelector(".map-inset__route")!.getAttribute("points")!.trim().split(/\s+/);
    expect(pts).toHaveLength(STATIONS.length);
  });

  it("plots a marker per station and labels the two ends", () => {
    const { svg } = renderMap();
    expect(svg.querySelectorAll(".map-inset__station")).toHaveLength(STATIONS.length);
    const labels = Array.from(svg.querySelectorAll(".map-inset__label")).map((t) => t.textContent);
    expect(labels).toEqual(["JTJ", "ED"]);
  });

  it("keeps every projected point inside the viewBox", () => {
    const { svg, width, height } = renderMap();
    for (const c of svg.querySelectorAll(".map-inset__station")) {
      const cx = Number(c.getAttribute("cx"));
      const cy = Number(c.getAttribute("cy"));
      expect(cx).toBeGreaterThanOrEqual(0);
      expect(cx).toBeLessThanOrEqual(width);
      expect(cy).toBeGreaterThanOrEqual(0);
      expect(cy).toBeLessThanOrEqual(height);
    }
  });

  it("uses the stations' real coordinates: south-west of JTJ plots down and left", () => {
    const { svg } = renderMap();
    const marks = Array.from(svg.querySelectorAll(".map-inset__station")).map((c) => ({
      cx: Number(c.getAttribute("cx")),
      cy: Number(c.getAttribute("cy")),
    }));
    // ED is both south (lower latitude) and west (lower longitude) of JTJ, so
    // it must plot further down and further left. Guards the projection's sign.
    expect(marks[3].cy).toBeGreaterThan(marks[0].cy);
    expect(marks[3].cx).toBeLessThan(marks[0].cx);
  });

  it("marks junctions with the larger radius", () => {
    const { svg } = renderMap();
    expect(svg.querySelectorAll(".map-inset__station--junction")).toHaveLength(4);
  });
});
