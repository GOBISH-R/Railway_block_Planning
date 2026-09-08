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
 *
 * AND THEN 34px WAS STILL TOO HIGH, which was worse than showing nothing.
 * A 150-minute block is 24.0px and a 240-minute one is 38.4px, so the label
 * appeared on the long blocks only -- 24 of the reference plan's 140. Long
 * blocks have the most slack and therefore the highest reliability, so the
 * only figure ever on screen was 1.00, and the timeline read as though every
 * block were certain. A reader had to click each block to find the ones at
 * 0.90.
 *
 * The fix is a shorter label rather than a lower bar for the same text:
 * `reliabilityLabel` drops the leading zero, so ".90" is ~15px at the 9px
 * label size and fits a 150-minute block with ~4px either side. 22 keeps that
 * padding honest while admitting every block length the planner can emit.
 */
export const MIN_WIDTH_FOR_RELIABILITY_LABEL = 22;

/**
 * Reliability as it appears ON a block: ".90", ".99", "1.0".
 *
 * The leading zero is dropped because it carries no information and costs
 * roughly a quarter of the available width -- which is the difference between
 * labelling every block and labelling only the widest ones. Full precision
 * stays in the aria-label and the Why panel, so nothing is lost for a screen
 * reader or for anyone who opens the block.
 */
export function reliabilityLabel(reliability: number): string {
  if (reliability >= 0.995) return "1.0";
  return reliability.toFixed(2).replace(/^0/, "");
}

export const HEADER_HEIGHT = 40;
export const LABEL_COLUMN_WIDTH = 132;

/* ---------------------------------------------------------------------------
 * Overview strip
 *
 * The detailed grid deliberately draws blocks large enough to read, which means
 * it can only ever show a few days at a time -- about 4 of 14 at 1280px. The
 * overview answers the other question ("what does the whole plan look like?")
 * at a scale where a block is a mark rather than a bar. Same section order,
 * same day axis, same block positions; only the scale differs.
 * ------------------------------------------------------------------------- */

/**
 * viewBox width, chosen to sit near the strip's real rendered width (794px at
 * 1024 up to ~1210px at 1440) so the day numbers render close to 1:1 rather
 * than being scaled down into illegibility.
 */
export const OVERVIEW_WIDTH = 900;

/** 2px is the floor: below it adjacent section rows merge into each other. */
export const OVERVIEW_ROW_HEIGHT = 2;

/** Band above the rows carrying the day numbers. */
export const OVERVIEW_HEADER_HEIGHT = 11;

/** So a short block stays visible even though it is only ~6.7px wide. */
export const OVERVIEW_MIN_MARK_WIDTH = 2;

export function overviewHeight(sectionCount: number): number {
  return OVERVIEW_HEADER_HEIGHT + sectionCount * OVERVIEW_ROW_HEIGHT;
}

export function overviewDayWidth(horizonDays: number): number {
  return OVERVIEW_WIDTH / horizonDays;
}

export function overviewX(day: number, minuteOfDay: number, horizonDays: number): number {
  const dayWidth = overviewDayWidth(horizonDays);
  return day * dayWidth + (minuteOfDay / MINUTES_PER_DAY) * dayWidth;
}

export function overviewMarkWidth(minutes: number, horizonDays: number): number {
  const dayWidth = overviewDayWidth(horizonDays);
  return Math.max(OVERVIEW_MIN_MARK_WIDTH, (minutes / MINUTES_PER_DAY) * dayWidth);
}

export function overviewRowY(rowIndex: number): number {
  return OVERVIEW_HEADER_HEIGHT + rowIndex * OVERVIEW_ROW_HEIGHT;
}

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
