import type { PlanResponse } from "../../api/types";
import { StatusBadge } from "../shared/StatusBadge";
import "./SummaryStrip.css";

/**
 * One dense row of the numbers a controller actually asks first, not a grid
 * of decorative KPI cards. Every value here is read directly from the plan
 * response with no derivation, so it can never disagree with the tables that
 * show the same figures elsewhere.
 */
export function SummaryStrip({ plan }: { plan: PlanResponse }) {
  const s = plan.summary;
  return (
    <div className="summary-strip">
      <StatusBadge status={plan.status} />

      <Metric label="Blocks" value={s.blocks} />
      <Metric label="Jobs done" value={s.jobs_done} />
      <Metric label="Deferred" value={s.jobs_deferred} tone={s.jobs_deferred > 0 ? "warning" : undefined} />
      <Metric label="Cross-dept" value={`${(s.cross_dept_share * 100).toFixed(0)}%`} />
      <Metric label="Traffic cost" value={s.traffic_cost.toFixed(1)} unit="wtm" />
      <Metric label="Min reliability" value={s.min_reliability.toFixed(2)} tone={s.min_reliability < plan.theta ? "error" : undefined} />
      <Metric label="Objective" value={plan.objective.toFixed(1)} unit="wtm" />

      <span className="summary-strip__timing" title="Wall-clock time for this plan">
        {formatSeconds(plan.stage_timings_s.total)} to plan
      </span>
    </div>
  );
}

function Metric({
  label,
  value,
  unit,
  tone,
}: {
  label: string;
  value: string | number;
  unit?: string;
  tone?: "warning" | "error";
}) {
  return (
    <div className={`summary-strip__metric ${tone ? `summary-strip__metric--${tone}` : ""}`}>
      <span className="summary-strip__label">{label}</span>
      <span className="summary-strip__value">
        {value}
        {unit && <span className="summary-strip__unit"> {unit}</span>}
      </span>
    </div>
  );
}

function formatSeconds(seconds: number | undefined): string {
  if (seconds == null) return "—";
  return seconds < 10 ? `${seconds.toFixed(1)}s` : `${Math.round(seconds)}s`;
}
