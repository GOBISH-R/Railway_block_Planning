import { useMemo, useState } from "react";
import type { DemandJob } from "../../api/types";
import type { StationPoint } from "./corridorProfile";
import { placeJobs, totalCorridorKm } from "./corridorProfile";
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
  const height = stripY + 40;

  const jobPoints = useMemo(() => {
    const placed = placeJobs(jobs, stations);
    return filterDept ? placed.filter((p) => p.job.dept === filterDept) : placed;
  }, [jobs, stations, filterDept]);

  const kmToX = (km: number) => (km / totalKm) * (width - 24) + 12;

  return (
    <div className="corridor-strip">
      <svg viewBox={`0 0 ${width} ${height}`} className="corridor-strip__svg" role="img"
           aria-label="Linear corridor diagram with pending maintenance jobs by department">
        {(["ENGG", "SNT", "TRD"] as const).map((dept) => (
          <text key={dept} x={2} y={DEPT_LANE[dept] * laneHeight + 14} className="corridor-strip__lane-label">
            {dept}
          </text>
        ))}

        <line x1={12} x2={width - 12} y1={stripY} y2={stripY} className="corridor-strip__line" />

        {stations.map((s) => (
          <g key={s.station_code}>
            <line
              x1={kmToX(s.km)} x2={kmToX(s.km)}
              y1={stripY - 5} y2={stripY + 5}
              className={s.is_junction ? "corridor-strip__tick corridor-strip__tick--junction" : "corridor-strip__tick"}
            />
            <text
              x={kmToX(s.km)}
              y={stripY + 18}
              className="corridor-strip__station-label"
              textAnchor="middle"
            >
              {s.station_code}
            </text>
          </g>
        ))}

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
