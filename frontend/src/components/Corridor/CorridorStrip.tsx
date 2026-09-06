import { useMemo, useState } from "react";
import type { DemandJob } from "../../api/types";
import type { StationPoint } from "./corridorProfile";
import {
  STATION_LABEL_BASELINE_DY,
  placeJobs,
  stationLabelRow,
  totalCorridorKm,
} from "./corridorProfile";
import "./CorridorStrip.css";

const DEPT_VAR: Record<string, string> = {
  ENGG: "var(--dept-engg)",
  SNT: "var(--dept-snt)",
  TRD: "var(--dept-trd)",
};
const DEPT_LANE: Record<string, number> = { ENGG: 0, SNT: 1, TRD: 2 };

/**
 * The corridor as a linear strip: real km positions, real station order.
 * More honest and more useful here than a geographic map, per the project's
 * own design brief -- the corridor genuinely is linear, and km offsets carry
 * real planning meaning (which the map cannot show at this scale).
 */
export function CorridorStrip({
  stations,
  jobs,
  filterDept,
}: {
  stations: StationPoint[];
  jobs: DemandJob[];
  filterDept: string | null;
}) {
  const [hovered, setHovered] = useState<DemandJob | null>(null);
  const totalKm = totalCorridorKm(stations);
  const width = 1180;
  const laneHeight = 22;
  const stripY = 3 * laneHeight + 34;
  // Room for the lower of the two label baselines plus its descenders.
  const height = stripY + STATION_LABEL_BASELINE_DY[1] + 11;

  const jobPoints = useMemo(() => {
    const placed = placeJobs(jobs, stations);
    return filterDept ? placed.filter((p) => p.job.dept === filterDept) : placed;
  }, [jobs, stations, filterDept]);

  // 20 units of margin either side, not 12: at the label size the end codes
  // (JTJ, ED) are centred on the first and last ticks and half of each hangs
  // outside them, which left JTJ only ~2 units clear of the viewBox edge.
  // Still a straight linear map of km, so every station keeps its true
  // relative position.
  const edgeMargin = 20;
  const kmToX = (km: number) => (km / totalKm) * (width - 2 * edgeMargin) + edgeMargin;

  return (
    <div className="corridor-strip">
      <svg viewBox={`0 0 ${width} ${height}`} className="corridor-strip__svg" role="img"
           aria-label="Linear corridor diagram with pending maintenance jobs by department">
        {(["ENGG", "SNT", "TRD"] as const).map((dept) => (
          <text key={dept} x={2} y={DEPT_LANE[dept] * laneHeight + 14} className="corridor-strip__lane-label">
            {dept}
          </text>
        ))}

        {/* Runs a little past the terminal ticks so the line reads as track
            rather than stopping dead on JTJ and ED. */}
        <line
          x1={edgeMargin - 8}
          x2={width - (edgeMargin - 8)}
          y1={stripY}
          y2={stripY}
          className="corridor-strip__line"
        />

        {stations.map((s, i) => {
          const x = kmToX(s.km);
          const row = stationLabelRow(i);
          const labelY = stripY + STATION_LABEL_BASELINE_DY[row];
          return (
            <g key={s.station_code}>
              <line
                x1={x} x2={x}
                y1={stripY - 5} y2={stripY + 5}
                className={s.is_junction ? "corridor-strip__tick corridor-strip__tick--junction" : "corridor-strip__tick"}
              />
              {row > 0 && (
                <line
                  x1={x} x2={x}
                  y1={stripY + 5} y2={labelY - 10}
                  className="corridor-strip__leader"
                />
              )}
              <text
                x={x}
                y={labelY}
                className="corridor-strip__station-label"
                textAnchor="middle"
              >
                {s.station_code}
              </text>
            </g>
          );
        })}

        {jobPoints.map(({ job, km }) => (
          <circle
            key={job.job_id}
            cx={kmToX(km)}
            cy={DEPT_LANE[job.dept] * laneHeight + 9}
            r={4}
            fill={DEPT_VAR[job.dept] ?? "var(--ink-2)"}
            className="corridor-strip__job"
            tabIndex={0}
            role="img"
            aria-label={`${job.job_id}, ${job.dept}, ${job.activity}, km ${km.toFixed(1)}`}
            onMouseEnter={() => setHovered(job)}
            onMouseLeave={() => setHovered(null)}
            onFocus={() => setHovered(job)}
            onBlur={() => setHovered(null)}
          />
        ))}
      </svg>

      <div className="corridor-strip__tooltip-slot" aria-live="polite">
        {hovered && (
          <span className="corridor-strip__tooltip">
            <strong>{hovered.job_id}</strong> &middot; {hovered.dept} &middot; {hovered.activity} &middot;{" "}
            {hovered.section_id} km {hovered.km_from.toFixed(1)} &middot; due day {hovered.due_day} &middot;{" "}
            criticality {hovered.criticality.toFixed(2)}
          </span>
        )}
      </div>
    </div>
  );
}
