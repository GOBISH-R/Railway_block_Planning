import { KpiCard, KpiGrid } from "../shared/KpiCard";
import { ErrorState, LoadingState } from "../shared/ViewStates";
import { scenarioLabel } from "../shared/scenarioLabel";
import type { CorridorResponse, PlanResponse } from "../../api/types";
import "./OverviewView.css";

/**
 * The whole system in one screen: what corridor, what demand, what the
 * optimiser decided, and what it cost the railway.
 *
 * Every figure comes from a response field. Nothing is derived here except
 * counting array lengths, and nothing is defaulted -- when the plan has not
 * been computed yet the plan half of the page says so rather than showing
 * zeros, because a zero block count is a real and different statement from
 * "not planned".
 */
export function OverviewView({
  corridor,
  plan,
  isPlanning,
  scenario,
  onOpenPlan,
}: {
  corridor: CorridorResponse;
  plan: PlanResponse | null;
  isPlanning: boolean;
  scenario: string;
  onOpenPlan: () => void;
}) {
  const availability = plan?.availability;

  return (
    <div className="overview">
      <header className="overview__head">
        <div>
          <h1 className="overview__title">Maintenance block planning</h1>
          <p className="overview__sub">
            {corridor.stations.length} stations &middot; {corridor.sections.length}{" "}
            section-lines &middot; scenario{" "}
            <strong>{scenarioLabel(scenario)}</strong>
          </p>
        </div>
      </header>

      <section className="overview__section" aria-labelledby="ov-corridor">
        <h2 className="overview__section-title" id="ov-corridor">
          Corridor
        </h2>
        <KpiGrid>
          <KpiCard label="Stations" value={corridor.stations.length} />
          <KpiCard
            label="Section-lines"
            value={corridor.sections.length}
            note="Each direction is planned separately"
          />
          <KpiCard
            label="Junctions"
            value={corridor.stations.filter((s) => s.is_junction).length}
          />
          <KpiCard
            label="Corridor length"
            value={corridor.sections
              .filter((s) => s.line === "UP")
              .reduce((total, s) => total + s.length_km, 0)
              .toFixed(1)}
            unit="km"
            note="UP direction, end to end"
          />
        </KpiGrid>
      </section>

      <section className="overview__section" aria-labelledby="ov-plan">
        <div className="overview__section-head">
          <h2 className="overview__section-title" id="ov-plan">
            Current plan
          </h2>
          <button className="overview__link" onClick={onOpenPlan}>
            Open block plan &rarr;
          </button>
        </div>

        {isPlanning ? (
          <LoadingState label="Planning…" />
        ) : !plan ? (
          <ErrorState
            title="No plan computed yet"
            detail="Open the Block Plan view and run a plan for this scenario."
          />
        ) : (
          <>
            <KpiGrid>
              <KpiCard
                label="Blocks"
                value={plan.summary.blocks}
                note={`${plan.status} · objective ${plan.objective.toFixed(1)}`}
                emphasis
              />
              <KpiCard
                label="Jobs completed"
                value={plan.summary.jobs_done}
                note={`of ${plan.summary.jobs_done + plan.summary.jobs_deferred} requested`}
                tone="positive"
              />
              <KpiCard
                label="Jobs deferred"
                value={plan.summary.jobs_deferred}
                tone={plan.summary.jobs_deferred > 0 ? "caution" : "neutral"}
              />
              <KpiCard
                label="Traffic cost"
                value={plan.summary.traffic_cost.toFixed(1)}
                note="Weighted train-minutes of delay"
              />
              <KpiCard
                label="Expected overrun"
                value={plan.summary.exp_overrun_cost.toFixed(1)}
                note="Modelled, before execution"
              />
              <KpiCard
                label="Minimum reliability"
                value={plan.summary.min_reliability.toFixed(2)}
                note={`Chance constraint θ = ${plan.theta.toFixed(2)}`}
                tone={
                  plan.summary.min_reliability >= plan.theta ? "positive" : "critical"
                }
              />
            </KpiGrid>

            {availability ? (
              <div className="overview__availability">
                <div className="overview__availability-figure">
                  {(availability.availability * 100).toFixed(1)}
                  <span className="overview__availability-unit">%</span>
                </div>
                <div className="overview__availability-body">
                  <div className="overview__availability-label">
                    Corridor asset availability
                  </div>
                  {/* The percentage never appears without the work figures.
                      On its own it is maximised by doing no maintenance. */}
                  <p className="overview__availability-note">
                    while completing{" "}
                    <strong>
                      {availability.jobs_done} of{" "}
                      {availability.jobs_done + availability.jobs_deferred}
                    </strong>{" "}
                    jobs, withdrawing{" "}
                    <strong>{availability.block_hours.toFixed(1)} section-hours</strong>{" "}
                    from a {(availability.capacity_minutes / 60).toLocaleString()}
                    -hour corridor and causing{" "}
                    <strong>
                      {availability.traffic_delay_minutes.toFixed(1)} weighted
                      delay-minutes
                    </strong>
                    .
                  </p>
                </div>
              </div>
            ) : null}
          </>
        )}
      </section>

      <section className="overview__section" aria-labelledby="ov-instance">
        <h2 className="overview__section-title" id="ov-instance">
          Problem size
        </h2>
        {plan ? (
          <KpiGrid>
            <KpiCard label="Jobs requested" value={plan.instance.base_jobs} />
            <KpiCard
              label="After rule expansion"
              value={plan.instance.jobs_after_pairing}
              note="Mandatory cross-department pairings added"
            />
            <KpiCard label="Bundles" value={plan.instance.bundles.toLocaleString()} />
            <KpiCard label="Windows priced" value={plan.instance.windows.toLocaleString()} />
            <KpiCard
              label="Columns"
              value={plan.instance.columns.toLocaleString()}
              note={`Survived θ with ${plan.instance.mc_samples.toLocaleString()} Monte Carlo samples`}
            />
          </KpiGrid>
        ) : (
          <p className="overview__muted">Available once a plan has been computed.</p>
        )}
      </section>
    </div>
  );
}
