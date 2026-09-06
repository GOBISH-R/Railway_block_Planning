import type { Movement } from "../../api/types";

const BUCKET_MIN = 30;
const BUCKETS_PER_DAY = 1440 / BUCKET_MIN;

/**
 * Per-section traffic density, bucketed into 30-minute bins across the day.
 *
 * The published timetable (and the /traffic response built from it) carries
 * a minute-of-day for each movement but no day-of-week field -- it is a
 * working timetable, which by nature repeats daily. So this density profile
 * is computed once per section and is drawn identically behind every day
 * column in the timeline, rather than implying (falsely) that traffic
 * differs day to day within the plan horizon.
 */
export function computeDensityBySection(movements: Movement[]): Map<string, number[]> {
  const bySection = new Map<string, number[]>();
  for (const m of movements) {
    let buckets = bySection.get(m.section_id);
    if (!buckets) {
      buckets = new Array(BUCKETS_PER_DAY).fill(0);
      bySection.set(m.section_id, buckets);
    }
    const bucket = Math.min(BUCKETS_PER_DAY - 1, Math.floor(m.enter_min / BUCKET_MIN));
    buckets[bucket] += 1;
  }
  return bySection;
}

export { BUCKET_MIN, BUCKETS_PER_DAY };
