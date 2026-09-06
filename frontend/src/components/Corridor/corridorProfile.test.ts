import { describe, expect, it } from "vitest";
import type { CorridorResponse, DemandJob } from "../../api/types";
import { buildStationProfile, placeJobs, totalCorridorKm } from "./corridorProfile";

function makeCorridor(): CorridorResponse {
  return {
    stations: [
      { station_code: "A", station_name: "Alpha", latitude: 0, longitude: 0, seq: 0, is_junction: false },
      { station_code: "B", station_name: "Beta", latitude: 0.1, longitude: 0.1, seq: 1, is_junction: true },
      { station_code: "C", station_name: "Gamma", latitude: 0.2, longitude: 0.2, seq: 2, is_junction: false },
    ],
    sections: [
      { section_id: "A-B-UP", from_station_code: "A", to_station_code: "B", line: "UP", length_km: 10, tracks: 2, electrified: true, is_single: false, headway_min: 5 },
      { section_id: "A-B-DN", from_station_code: "A", to_station_code: "B", line: "DN", length_km: 10, tracks: 2, electrified: true, is_single: false, headway_min: 5 },
      { section_id: "B-C-UP", from_station_code: "B", to_station_code: "C", line: "UP", length_km: 15, tracks: 2, electrified: true, is_single: false, headway_min: 5 },
      { section_id: "B-C-DN", from_station_code: "B", to_station_code: "C", line: "DN", length_km: 15, tracks: 2, electrified: true, is_single: false, headway_min: 5 },
    ],
  };
}

describe("buildStationProfile", () => {
  it("accumulates km from one direction only, not double-counted across UP+DN", () => {
    const profile = buildStationProfile(makeCorridor());
    expect(profile.map((p) => p.station_code)).toEqual(["A", "B", "C"]);
    expect(profile[0].km).toBe(0);
    expect(profile[1].km).toBe(10); // A-B length, counted once despite two section rows
    expect(profile[2].km).toBe(25); // + B-C length
  });

  it("orders stations by sequence, not by appearance in the sections list", () => {
    const corridor = makeCorridor();
    // Deliberately shuffle station order to confirm seq (not array order) governs.
    corridor.stations.reverse();
    const profile = buildStationProfile(corridor);
    expect(profile.map((p) => p.station_code)).toEqual(["A", "B", "C"]);
  });
});

describe("totalCorridorKm", () => {
  it("equals the last station's cumulative km", () => {
    const profile = buildStationProfile(makeCorridor());
    expect(totalCorridorKm(profile)).toBe(25);
  });

  it("is zero for an empty station list", () => {
    expect(totalCorridorKm([])).toBe(0);
  });
});

function makeJob(overrides: Partial<DemandJob>): DemandJob {
  return {
    job_id: "J1",
    dept: "ENGG",
    activity: "THROUGH_TAMPING",
    section_id: "A-B-UP",
    km_from: 2,
    km_to: 3,
    needs_T: true,
    needs_P: false,
    needs_D: false,
    needs_train_movements: false,
    needs_live_ohe: false,
    duration_mean_min: 60,
    duration_sd_min: 10,
    due_day: 0,
    criticality: 1,
    priority: "NORMAL",
    uncertainty_level: "MEDIUM",
    resources: [],
    ...overrides,
  };
}

describe("placeJobs", () => {
  it("places a job at its section's start km plus its own km_from", () => {
    const profile = buildStationProfile(makeCorridor());
    const [placed] = placeJobs([makeJob({ section_id: "B-C-DN", km_from: 4 })], profile);
    // B starts at km 10, so a job 4km into B-C sits at km 14.
    expect(placed.km).toBe(14);
  });

  it("is direction-independent: UP and DN on the same physical section place identically", () => {
    const profile = buildStationProfile(makeCorridor());
    const up = placeJobs([makeJob({ section_id: "A-B-UP", km_from: 3 })], profile)[0];
    const dn = placeJobs([makeJob({ section_id: "A-B-DN", km_from: 3 })], profile)[0];
    expect(up.km).toBe(dn.km);
  });

  it("drops a job whose section is not on the corridor rather than throwing", () => {
    const profile = buildStationProfile(makeCorridor());
    const placed = placeJobs([makeJob({ section_id: "X-Y-UP" })], profile);
    expect(placed).toHaveLength(0);
  });
});
