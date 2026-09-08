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
      {/* Availability sits AFTER the work figures, deliberately. Read left to
          right the row says what was done and then what it cost the line --
          the percentage arriving first would invite reading it alone, which is
          the one way this metric misleads.

          Omitted entirely if the response carries no availability object. The
          contract says it is always there, but a missing measurement rendered
          as 0% would be a fabricated one, and blanking the whole plan view
          over an absent field would be worse than showing the rest of it. */}
      {plan.availability ? (
        <Metric
          label="Availability"
          value={`${(plan.availability.availability * 100).toFixed(2)}%`}
          title={plan.availability.headline}
        />
      ) : null}

      <span
        className="summary-strip__timing"
        title={
          plan.cache_hit
            ? "Served from cache. The time shown is how long this scenario took the first time it was computed, not this request's latency."
            : "Wall-clock time for this plan"
        }
      >
        {plan.cache_hit ? (
          <>cached &middot; {formatSeconds(plan.stage_timings_s.total)} to originally compute</>
        ) : (
          <>{formatSeconds(plan.stage_timings_s.total)} to plan</>
        )}
      </span>
    </div>
  );
}

function Metric({
  label,
  value,
  unit,
  tone,
  title,
}: {
  title?: string;
  label: string;
  value: string | number;
  unit?: string;
  tone?: "warning" | "error";
}) {
  return (
    <div
      className={`summary-strip__metric ${tone ? `summary-strip__metric--${tone}` : ""}`}
      title={title}
    >
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
