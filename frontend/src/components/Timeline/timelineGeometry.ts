import type { SectionMeta } from "../../api/types";

export const MINUTES_PER_DAY = 1440;

/**
 * Horizontal scale. Every block in every scenario is either 150 or 240 minutes
 * long, so this constant is really choosing just two bar widths: 24px and
 * 38.4px.
 *
 * Widening is safe at any scale: two blocks on the same section and day never
 * overlap in time, and x is a linear map of time, so they cannot be made to
 * overlap by scaling.
 *
 * The trade-off is coverage -- a wider day axis shows fewer days without
 * scrolling. 0.16 is the smallest scale at which a three-department block's
 * bands are legible (see BLOCK_BAR_HEIGHT) and a 240-min block can carry its
 * reliability figure with real padding. Fitting more of the plan on screen is
 * a separate problem that needs an overview or a zoom, not a smaller scale.
 */
export const PX_PER_MIN = 0.16;
export const DAY_WIDTH = MINUTES_PER_DAY * PX_PER_MIN;
export const ROW_HEIGHT = 28;

/**
 * Divides evenly for the bundle sizes that actually occur: 3 departments give
 * 7px bands, 2 give 10.5px, 1 fills the bar.
 */
export const BLOCK_BAR_HEIGHT = 21;

/**
 * A block carries its reliability figure only if the bar is at least this
 * wide. "0.99" at the 9px label size is ~20px, so 34px leaves ~7px of padding
 * either side; at 24px the text would run edge to edge.
 *
 * The previous threshold was 30px, which no block could ever reach (the widest
 * was 27.6px), so the label never rendered at all. Any change to PX_PER_MIN
 * must keep this reachable -- `timelineGeometry.test.ts` asserts it against
 * the real 240-minute block width.
 */
export const MIN_WIDTH_FOR_RELIABILITY_LABEL = 34;

export const HEADER_HEIGHT = 40;
export const LABEL_COLUMN_WIDTH = 132;

/** Section-lines in true corridor order: by station sequence, UP before DN. */
export function orderSections(sections: SectionMeta[], stationSeq: Map<string, number>): SectionMeta[] {
  return [...sections].sort((a, b) => {
    const seqA = stationSeq.get(a.from_station_code) ?? 0;
    const seqB = stationSeq.get(b.from_station_code) ?? 0;
    if (seqA !== seqB) return seqA - seqB;
    return a.line.localeCompare(b.line);
  });
}

export function dayLeft(day: number): number {
  return day * DAY_WIDTH;
}

export function minutesToX(day: number, minuteOfDay: number): number {
  return dayLeft(day) + minuteOfDay * PX_PER_MIN;
}

export function durationToWidth(minutes: number): number {
  return minutes * PX_PER_MIN;
}
