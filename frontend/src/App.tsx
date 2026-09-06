import { useState } from "react";
import { AppShell, type ViewKey } from "./components/Shell/AppShell";
import { CorridorView } from "./components/Corridor/CorridorView";
import { EvidenceView } from "./components/Evidence/EvidenceView";
import { TimelineView } from "./components/Timeline/TimelineView";
import { WhyPanel, type WhySelection } from "./components/WhyPanel/WhyPanel";
import { ErrorState, LoadingState } from "./components/shared/ViewStates";
import { usePlanningState } from "./state/usePlanningState";

export default function App() {
  const [view, setView] = useState<ViewKey>("timeline");
  const [whySelection, setWhySelection] = useState<WhySelection | null>(null);
  const {
    corridor,
    scenarios,
    scenario,
    theta,
    horizonDays,
    plan,
    isLoadingReference,
    isPlanning,
    error,
    setScenario,
    setTheta,
    setHorizonDays,
    replan,
  } = usePlanningState();

  if (isLoadingReference) {
    return <LoadingState label="Loading corridor data…" />;
  }
  if (error && !corridor) {
    return <ErrorState title="Could not reach the planning service" detail={error} />;
  }
  if (!corridor) {
    return <ErrorState title="No corridor data" />;
  }

  return (
    <AppShell active={view} onNavigate={setView}>
      {view === "timeline" && (
        <TimelineView
          corridor={corridor}
          scenarios={scenarios}
          scenario={scenario}
          onScenarioChange={setScenario}
          theta={theta}
          onThetaChange={setTheta}
          horizonDays={horizonDays}
          onHorizonChange={setHorizonDays}
          plan={plan}
          isPlanning={isPlanning}
          onReplan={replan}
          selectedBlockId={whySelection?.kind === "block" ? whySelection.blockId : null}
          onSelectBlock={(blockId) => {
            if (!plan) return;
            setWhySelection({ kind: "block", planId: plan.plan_id, blockId });
          }}
          onSelectJob={(jobId) => {
            if (!plan) return;
            setWhySelection({ kind: "job", planId: plan.plan_id, jobId });
          }}
        />
      )}

      {view === "corridor" && (
        <CorridorView
          corridor={corridor}
          scenarios={scenarios}
          scenario={scenario}
          onScenarioChange={setScenario}
        />
      )}

      {view === "evidence" && <EvidenceView />}

      {whySelection && (
        <WhyPanel
          selection={whySelection}
          onSelect={setWhySelection}
          onClose={() => setWhySelection(null)}
        />
      )}
    </AppShell>
  );
}
