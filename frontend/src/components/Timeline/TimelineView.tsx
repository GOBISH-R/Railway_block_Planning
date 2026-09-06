import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { CorridorResponse, Movement, PlanResponse, ScenarioRow } from "../../api/types";
import { ErrorState, LoadingState } from "../shared/ViewStates";
import { ControlsBar } from "./ControlsBar";
import { DeferredList } from "./DeferredList";
import { SummaryStrip } from "./SummaryStrip";
import { TimelineGrid } from "./TimelineGrid";
import "./TimelineView.css";

export function TimelineView({
  corridor,
  scenarios,
  scenario,
  onScenarioChange,
  theta,
  onThetaChange,
  horizonDays,
  onHorizonChange,
  plan,
  isPlanning,
  onReplan,
  onSelectBlock,
  onSelectJob,
  selectedBlockId,
}: {
  corridor: CorridorResponse;
  scenarios: ScenarioRow[];
  scenario: string;
  onScenarioChange: (s: string) => void;
  theta: number;
  onThetaChange: (t: number) => void;
  horizonDays: number;
  onHorizonChange: (h: number) => void;
  plan: PlanResponse | null;
  isPlanning: boolean;
  onReplan: () => void;
  onSelectBlock: (blockId: string) => void;
  onSelectJob: (jobId: string) => void;
  selectedBlockId: string | null;
}) {
  const [movements, setMovements] = useState<Movement[]>([]);

  useEffect(() => {
    let cancelled = false;
    void api.traffic(scenario).then((res) => {
      if (!cancelled) setMovements(res.movements);
    });
    return () => {
      cancelled = true;
    };
  }, [scenario]);

  return (
    <div className="timeline-view">
      <ControlsBar
        scenarios={scenarios}
        scenario={scenario}
        onScenarioChange={onScenarioChange}
        theta={theta}
        onThetaChange={onThetaChange}
        horizonDays={horizonDays}
        onHorizonChange={onHorizonChange}
        onReplan={onReplan}
        isPlanning={isPlanning}
      />

      {plan && <SummaryStrip plan={plan} />}

      <div className="timeline-view__body">
        {isPlanning && !plan && <LoadingState label="Building the initial plan…" />}
        {isPlanning && plan && (
          <div className="timeline-view__replanning-veil">
            <LoadingState label="Re-planning…" />
          </div>
        )}
        {!isPlanning && !plan && (
          <ErrorState title="No plan yet" detail="Press Re-plan to run the optimiser." />
        )}
        {plan && (
          <div className="timeline-view__content" aria-hidden={isPlanning}>
            <TimelineGrid
              corridor={corridor}
              blocks={plan.blocks}
              movements={movements}
              horizonDays={plan.horizon_days}
              selectedBlockId={selectedBlockId}
              onSelectBlock={onSelectBlock}
            />
            <DeferredList deferred={plan.deferred} onSelectJob={onSelectJob} />
          </div>
        )}
      </div>

      <footer className="timeline-view__legend">
        <span className="timeline-view__legend-title">Department</span>
        <LegendSwatch color="var(--dept-engg)" label="Engineering (ENGG)" />
        <LegendSwatch color="var(--dept-snt)" label="Signal & Telecom (SNT)" />
        <LegendSwatch color="var(--dept-trd)" label="Traction Distribution (TRD)" />
        <span className="timeline-view__legend-note">
          Shading behind blocks: real-timetable traffic density (repeats daily)
        </span>
      </footer>
    </div>
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="timeline-view__legend-item">
      <span className="timeline-view__legend-swatch" style={{ background: color }} />
      {label}
    </span>
  );
}
