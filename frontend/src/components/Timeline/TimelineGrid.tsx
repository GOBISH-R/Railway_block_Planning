import { useMemo } from "react";
import type { CorridorResponse, Movement, PlanBlock } from "../../api/types";
import {
  BLOCK_BAR_HEIGHT,
  DAY_WIDTH,
  HEADER_HEIGHT,
  LABEL_COLUMN_WIDTH,
  MINUTES_PER_DAY,
  MIN_WIDTH_FOR_RELIABILITY_LABEL,
  reliabilityLabel,
  ROW_HEIGHT,
  durationToWidth,
  minutesToX,
  orderSections,
} from "./timelineGeometry";
import { BUCKET_MIN, computeDensityBySection } from "./trafficDensity";
import "./TimelineGrid.css";

const DEPT_VAR: Record<string, string> = {
  ENGG: "var(--dept-engg)",
  SNT: "var(--dept-snt)",
  TRD: "var(--dept-trd)",
};

export function TimelineGrid({
  corridor,
  blocks,
  movements,
  horizonDays,
  selectedBlockId,
  onSelectBlock,
}: {
  corridor: CorridorResponse;
  blocks: PlanBlock[];
  movements: Movement[];
  horizonDays: number;
  selectedBlockId: string | null;
  onSelectBlock: (blockId: string) => void;
}) {
  const stationSeq = useMemo(
    () => new Map(corridor.stations.map((s) => [s.station_code, s.seq])),
    [corridor.stations]
  );
  const sections = useMemo(
    () => orderSections(corridor.sections, stationSeq),
    [corridor.sections, stationSeq]
  );
  const rowIndex = useMemo(
    () => new Map(sections.map((s, i) => [s.section_id, i])),
    [sections]
  );
  const blocksBySection = useMemo(() => {
    const map = new Map<string, PlanBlock[]>();
    for (const b of blocks) {
      const list = map.get(b.section_id) ?? [];
      list.push(b);
      map.set(b.section_id, list);
    }
    return map;
  }, [blocks]);
  const density = useMemo(() => computeDensityBySection(movements), [movements]);

  const bodyWidth = horizonDays * DAY_WIDTH;
  const bodyHeight = sections.length * ROW_HEIGHT;

  return (
    <div className="tgrid" role="group" aria-label="Plan timeline">
      <div className="tgrid__scroll">
        <div
          className="tgrid__grid"
          style={{
            gridTemplateColumns: `${LABEL_COLUMN_WIDTH}px ${bodyWidth}px`,
            gridTemplateRows: `${HEADER_HEIGHT}px ${bodyHeight}px`,
          }}
        >
          <div className="tgrid__corner">
            <span>Section-line</span>
          </div>

          <div className="tgrid__header" style={{ width: bodyWidth }}>
            <svg width={bodyWidth} height={HEADER_HEIGHT} className="tgrid__header-svg">
              {Array.from({ length: horizonDays }, (_, day) => (
                <g key={day}>
                  <line
                    x1={day * DAY_WIDTH}
                    x2={day * DAY_WIDTH}
                    y1={0}
                    y2={HEADER_HEIGHT}
                    className="tgrid__day-boundary"
                  />
                  <text x={day * DAY_WIDTH + 6} y={16} className="tgrid__day-label">
                    Day {day}
                  </text>
                  {[6, 12, 18].map((h) => (
                    <text
                      key={h}
                      x={day * DAY_WIDTH + h * 60 * (DAY_WIDTH / MINUTES_PER_DAY)}
                      y={32}
                      className="tgrid__hour-label"
                    >
                      {String(h).padStart(2, "0")}:00
                    </text>
                  ))}
                </g>
              ))}
            </svg>
          </div>

          <div className="tgrid__labels" style={{ height: bodyHeight }}>
            {sections.map((s) => (
              <div key={s.section_id} className="tgrid__label-row" style={{ height: ROW_HEIGHT }}>
                <span className="tgrid__label-text" title={`${s.section_id} · ${s.length_km.toFixed(1)} km`}>
                  {s.from_station_code}&rarr;{s.to_station_code}
                </span>
                <span className="tgrid__label-line">{s.line}</span>
              </div>
            ))}
          </div>

          <div className="tgrid__body" style={{ width: bodyWidth, height: bodyHeight }}>
            <svg width={bodyWidth} height={bodyHeight} className="tgrid__body-svg">
              {/* row separators */}
              {sections.map((s, i) => (
                <line
                  key={s.section_id}
                  x1={0}
                  x2={bodyWidth}
                  y1={(i + 1) * ROW_HEIGHT}
                  y2={(i + 1) * ROW_HEIGHT}
                  className="tgrid__row-line"
                />
              ))}

              {/* day boundaries */}
              {Array.from({ length: horizonDays + 1 }, (_, day) => (
                <line
                  key={day}
                  x1={day * DAY_WIDTH}
                  x2={day * DAY_WIDTH}
                  y1={0}
                  y2={bodyHeight}
                  className="tgrid__day-boundary tgrid__day-boundary--body"
                />
              ))}

              {/* traffic density: identical profile repeated each day, per section row */}
              {sections.map((s, i) => {
                const buckets = density.get(s.section_id);
                if (!buckets) return null;
                const max = Math.max(1, ...buckets);
                const y = i * ROW_HEIGHT;
                return Array.from({ length: horizonDays }, (_, day) =>
                  buckets.map((count, b) => {
                    if (count === 0) return null;
                    const x = day * DAY_WIDTH + b * BUCKET_MIN * (DAY_WIDTH / MINUTES_PER_DAY);
                    const w = BUCKET_MIN * (DAY_WIDTH / MINUTES_PER_DAY);
                    return (
                      <rect
                        key={`${day}-${b}`}
                        x={x}
                        y={y}
                        width={w}
                        height={ROW_HEIGHT}
                        className="tgrid__density"
                        opacity={(count / max) * 0.35}
                      />
                    );
                  })
                );
              })}

              {/* blocks */}
              {sections.map((s) => {
                const rowBlocks = blocksBySection.get(s.section_id);
                if (!rowBlocks) return null;
                const i = rowIndex.get(s.section_id)!;
                const y = i * ROW_HEIGHT + (ROW_HEIGHT - BLOCK_BAR_HEIGHT) / 2;
                return rowBlocks.map((block) => {
                  const x = minutesToX(block.day, block.start_min);
                  const w = durationToWidth(block.length);
                  const isSelected = block.block_id === selectedBlockId;
                  // Departments are stacked as full-width horizontal bands
                  // rather than side-by-side vertical stripes. Vertical
                  // stripes subdivided the block's width -- the axis already
                  // carrying 14 days of time -- so a three-department bar
                  // became three ~6px slivers that read as three separate
                  // narrow blocks, which is the opposite of what the bundle
                  // means. Banding gives every department the block's full
                  // width and keeps the bar reading as one object.
                  const bandH = BLOCK_BAR_HEIGHT / block.dept_mix.length;
                  return (
                    <g
                      key={block.block_id}
                      className="tgrid__block"
                      tabIndex={0}
                      role="button"
                      aria-label={`Block ${block.block_id}, ${s.from_station_code} to ${s.to_station_code}, day ${block.day}, ${block.length} minutes, reliability ${block.reliability.toFixed(2)}`}
                      aria-pressed={isSelected}
                      onClick={() => onSelectBlock(block.block_id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onSelectBlock(block.block_id);
                        }
                      }}
                    >
                      {block.dept_mix.map((dept, si) => (
                        <rect
                          key={dept}
                          x={x}
                          y={y + si * bandH}
                          width={w}
                          height={bandH}
                          fill={DEPT_VAR[dept] ?? "var(--ink-2)"}
                        />
                      ))}
                      <rect
                        x={x}
                        y={y}
                        width={w}
                        height={BLOCK_BAR_HEIGHT}
                        className={`tgrid__block-outline ${isSelected ? "tgrid__block-outline--selected" : ""}`}
                        fill="none"
                      />
                      {w >= MIN_WIDTH_FOR_RELIABILITY_LABEL && (
                        <text
                          x={x + w / 2}
                          y={y + BLOCK_BAR_HEIGHT / 2}
                          textAnchor="middle"
                          dominantBaseline="central"
                          className="tgrid__block-label"
                        >
                          {reliabilityLabel(block.reliability)}
                        </text>
                      )}
                    </g>
                  );
                });
              })}
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
}
