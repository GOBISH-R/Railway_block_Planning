import { useMemo } from "react";
import type { CorridorResponse, PlanBlock } from "../../api/types";
import {
  OVERVIEW_HEADER_HEIGHT,
  OVERVIEW_WIDTH,
  orderSections,
  overviewDayWidth,
  overviewHeight,
  overviewMarkWidth,
  overviewRowY,
  overviewX,
} from "./timelineGeometry";
import "./TimelineOverview.css";

/**
 * The whole plan at a glance: every day, every section-line, every block.
 *
 * The detailed grid draws blocks large enough to read, so it can only show
 * about four of fourteen days at once. This strip trades bar size for
 * completeness -- a block becomes a ~7px mark -- and answers the question the
 * detailed grid cannot: where in the fortnight, and on which parts of the
 * corridor, does the work actually fall?
 *
 * Department colour is deliberately not carried over. At a 2px row height hue
 * is not readable, and the one thing worth encoding at this scale is which
 * blocks bundle more than one department, since that is what the plan is for.
 * Which departments those are is the detailed grid's job, and the Why panel's.
 */
export function TimelineOverview({
  corridor,
  blocks,
  horizonDays,
}: {
  corridor: CorridorResponse;
  blocks: PlanBlock[];
  horizonDays: number;
}) {
  const stationSeq = useMemo(
    () => new Map(corridor.stations.map((s) => [s.station_code, s.seq])),
    [corridor.stations]
  );
  // The same helper the detailed grid uses, so the two share a row order by
  // construction rather than by coincidence.
  const sections = useMemo(
    () => orderSections(corridor.sections, stationSeq),
    [corridor.sections, stationSeq]
  );
  const rowIndex = useMemo(
    () => new Map(sections.map((s, i) => [s.section_id, i])),
    [sections]
  );

  const height = overviewHeight(sections.length);
  const dayWidth = overviewDayWidth(horizonDays);

  // Single-department marks first so the multi-department ones are never
  // painted over by a neighbouring row's pale mark.
  const marks = useMemo(() => {
    const drawn = blocks
      .filter((b) => rowIndex.has(b.section_id))
      .map((b) => ({
        block: b,
        multi: b.dept_mix.length > 1,
        x: overviewX(b.day, b.start_min, horizonDays),
        y: overviewRowY(rowIndex.get(b.section_id)!),
        w: overviewMarkWidth(b.length, horizonDays),
      }));
    return [...drawn.filter((m) => !m.multi), ...drawn.filter((m) => m.multi)];
  }, [blocks, rowIndex, horizonDays]);

  const multiCount = marks.filter((m) => m.multi).length;

  return (
    <section className="toverview">
      <div className="toverview__caption">
        <span className="toverview__title">Whole plan</span>
        <span className="toverview__meta">
          {horizonDays} days &middot; {sections.length} section-lines &middot; {blocks.length} blocks
        </span>
        <span className="toverview__key">
          <span className="toverview__key-item">
            <span className="toverview__swatch toverview__swatch--single" />
            single department
          </span>
          <span className="toverview__key-item">
            <span className="toverview__swatch toverview__swatch--multi" />
            multi-department ({multiCount})
          </span>
        </span>
      </div>

      <svg
        viewBox={`0 0 ${OVERVIEW_WIDTH} ${height}`}
        className="toverview__svg"
        role="img"
        aria-label={
          `Whole-plan overview: ${blocks.length} blocks across ${horizonDays} days ` +
          `and ${sections.length} section-lines, of which ${multiCount} carry more than ` +
          `one department. The detailed timeline below carries the same plan at full size.`
        }
      >
        {Array.from({ length: horizonDays + 1 }, (_, day) => (
          <line
            key={day}
            x1={day * dayWidth}
            x2={day * dayWidth}
            y1={OVERVIEW_HEADER_HEIGHT - 3}
            y2={height}
            className="toverview__day-boundary"
          />
        ))}

        {Array.from({ length: horizonDays }, (_, day) => (
          <text
            key={day}
            x={day * dayWidth + 3}
            y={OVERVIEW_HEADER_HEIGHT - 3}
            className="toverview__day-label"
          >
            {day}
          </text>
        ))}

        {marks.map((m) => (
          <rect
            key={m.block.block_id}
            x={m.x}
            y={m.y}
            width={m.w}
            height={2}
            className={
              m.multi ? "toverview__mark toverview__mark--multi" : "toverview__mark"
            }
          />
        ))}
      </svg>
    </section>
  );
}
