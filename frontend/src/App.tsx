import { useState } from "react";
import { AppShell, type ViewKey } from "./components/Shell/AppShell";
import { OverviewView } from "./components/Overview/OverviewView";
import { CorridorView } from "./components/Corridor/CorridorView";
import { TimelineView } from "./components/Timeline/TimelineView";
import { WhyPanel, type WhySelection } from "./components/WhyPanel/WhyPanel";
import { ErrorState, LoadingState } from "./components/shared/ViewStates";
import { ThemeToggle } from "./components/shared/ThemeToggle";
import { usePlanningState } from "./state/usePlanningState";
import { useTheme } from "./state/useTheme";

export default function App() {
  const [view, setView] = useState<ViewKey>("overview");
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
  // Runs before the early returns below, so the theme control stays available
  // while reference data is loading or the planning service is unreachable.
  const { preference, setPreference } = useTheme();

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
    <AppShell
      active={view}
      onNavigate={setView}
      headerRight={<ThemeToggle preference={preference} onChange={setPreference} />}
    >
      {view === "overview" && (
        <OverviewView
          corridor={corridor}
          plan={plan}
          isPlanning={isPlanning}
          scenario={scenario}
          onOpenPlan={() => setView("timeline")}
        />
      )}

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
