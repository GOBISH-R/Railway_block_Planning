import type { CorridorResponse, DemandJob, SectionMeta } from "../../api/types";

export interface StationPoint {
  station_code: string;
  station_name: string;
  km: number;
  is_junction: boolean;
  latitude: number;
  longitude: number;
}

export interface JobPoint {
  job: DemandJob;
  km: number;
}

/**
 * Cumulative km along the physical corridor, from real section lengths.
 *
 * Each physical section appears twice in the dataset (UP and DN carry the
 * same length_km) -- one direction is picked here to avoid double-counting,
 * since the strip represents physical distance along the line, not the two
 * separate running lines.
 */
export function buildStationProfile(corridor: CorridorResponse): StationPoint[] {
  const upSections = new Map<string, SectionMeta>();
  for (const s of corridor.sections) {
    if (s.line === "UP" || !upSections.has(s.from_station_code)) {
      upSections.set(s.from_station_code, s);
    }
  }

  const ordered = [...corridor.stations].sort((a, b) => a.seq - b.seq);
  let km = 0;
  const points: StationPoint[] = [];
  for (const station of ordered) {
    points.push({
      station_code: station.station_code,
      station_name: station.station_name,
      km,
      is_junction: station.is_junction,
      latitude: station.latitude,
      longitude: station.longitude,
    });
    const section = upSections.get(station.station_code);
    if (section) km += section.length_km;
  }
  return points;
}

/** Maps every job onto the physical corridor km axis, direction-independent. */
export function placeJobs(jobs: DemandJob[], stations: StationPoint[]): JobPoint[] {
  const startKmByStation = new Map(stations.map((s) => [s.station_code, s.km]));
  return jobs
    .map((job) => {
      const fromCode = job.section_id.split("-")[0];
      const base = startKmByStation.get(fromCode);
      if (base == null) return null;
      return { job, km: base + job.km_from };
    })
    .filter((p): p is JobPoint => p !== null);
}

export function totalCorridorKm(stations: StationPoint[]): number {
  return stations.length ? stations[stations.length - 1].km : 0;
}
