import type { SectionMeta } from "../../api/types";

export const MINUTES_PER_DAY = 1440;
export const PX_PER_MIN = 0.115; // ~166px per day -- wide enough for a 150-min bar to carry a label
export const DAY_WIDTH = MINUTES_PER_DAY * PX_PER_MIN;
export const ROW_HEIGHT = 24;
export const BLOCK_BAR_HEIGHT = 16;
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
