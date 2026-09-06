import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { CorridorResponse, PlanResponse, ScenarioRow } from "../api/types";

const DEFAULT_SCENARIO = "NORMAL_TRAFFIC";
const DEFAULT_THETA = 0.9;
const DEFAULT_HORIZON = 14;
const DEFAULT_MAX_BUNDLE = 5;
const DEFAULT_MC_SAMPLES = 1500;

export interface PlanningState {
  corridor: CorridorResponse | null;
  scenarios: ScenarioRow[];
  scenario: string;
  theta: number;
  horizonDays: number;
  plan: PlanResponse | null;
  isLoadingReference: boolean;
  isPlanning: boolean;
  error: string | null;
  setScenario: (s: string) => void;
  setTheta: (t: number) => void;
  setHorizonDays: (h: number) => void;
  replan: () => void;
}

/**
 * Owns the one piece of shared state every view depends on: the current
 * scenario/theta/horizon selection and the plan it produced. Reference data
 * (corridor geography, scenario list) is fetched once; a plan is fetched
 * whenever the controls change, via an explicit Re-plan action -- there is no
 * polling and no background refetch, matching the "nothing is live" stance in
 * the project's own frontend brief.
 */
export function usePlanningState(): PlanningState {
  const [corridor, setCorridor] = useState<CorridorResponse | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioRow[]>([]);
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [theta, setTheta] = useState(DEFAULT_THETA);
  const [horizonDays, setHorizonDays] = useState(DEFAULT_HORIZON);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [isLoadingReference, setIsLoadingReference] = useState(true);
  const [isPlanning, setIsPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Guards against a slow first plan resolving after a second one was
  // already requested (e.g. the user drags theta twice quickly).
  const requestId = useRef(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [corridorRes, scenariosRes] = await Promise.all([
          api.corridor(),
          api.scenarios(),
        ]);
        if (cancelled) return;
        setCorridor(corridorRes);
        setScenarios(scenariosRes.scenarios);
      } catch (err) {
        if (!cancelled) setError(describeError(err));
      } finally {
        if (!cancelled) setIsLoadingReference(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const runPlan = useCallback(
    async (nextScenario: string, nextTheta: number, nextHorizon: number) => {
      const myRequest = ++requestId.current;
      setIsPlanning(true);
      setError(null);
      try {
        const result = await api.createPlan({
          scenario: nextScenario,
          horizon_days: nextHorizon,
          theta: nextTheta,
          max_bundle_size: DEFAULT_MAX_BUNDLE,
          mc_samples: DEFAULT_MC_SAMPLES,
        });
        if (requestId.current === myRequest) {
          setPlan(result);
        }
      } catch (err) {
        if (requestId.current === myRequest) {
          setError(describeError(err));
        }
      } finally {
        if (requestId.current === myRequest) {
          setIsPlanning(false);
        }
      }
    },
    []
  );

  // First plan, once reference data is in and before any user interaction.
  useEffect(() => {
    if (!isLoadingReference && !plan) {
      void runPlan(scenario, theta, horizonDays);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoadingReference]);

  const replan = useCallback(() => {
    void runPlan(scenario, theta, horizonDays);
  }, [runPlan, scenario, theta, horizonDays]);

  return {
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
  };
}

function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong talking to the planning service.";
}
