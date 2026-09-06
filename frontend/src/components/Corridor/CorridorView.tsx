import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { CorridorResponse, DemandJob, ScenarioRow } from "../../api/types";
import { Select } from "../shared/Controls";
import { ErrorState, LoadingState } from "../shared/ViewStates";
import { buildStationProfile } from "./corridorProfile";
import { CorridorStrip } from "./CorridorStrip";
import { DemandTable } from "./DemandTable";
import { MapInset } from "./MapInset";
import "./CorridorView.css";

const DEPTS = ["ENGG", "SNT", "TRD"] as const;

export function CorridorView({
  corridor,
  scenarios,
  scenario,
  onScenarioChange,
}: {
  corridor: CorridorResponse;
  scenarios: ScenarioRow[];
  scenario: string;
  onScenarioChange: (s: string) => void;
}) {
  const [jobs, setJobs] = useState<DemandJob[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filterDept, setFilterDept] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setJobs(null);
    setError(null);
    api
      .demand(scenario)
      .then((res) => {
        if (!cancelled) setJobs(res.jobs);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load demand.");
      });
    return () => {
      cancelled = true;
    };
  }, [scenario]);

  const stations = useMemo(() => buildStationProfile(corridor), [corridor]);

  return (
    <div className="corridor-view">
      <div className="corridor-view__controls">
        <Select
          label="Scenario"
          value={scenario}
          onChange={onScenarioChange}
          options={scenarios.map((s) => ({ value: s.name, label: s.name }))}
        />
        <div className="corridor-view__dept-filter" role="group" aria-label="Filter by department">
          <button
            className={`corridor-view__filter-chip ${filterDept === null ? "corridor-view__filter-chip--active" : ""}`}
            onClick={() => setFilterDept(null)}
          >
            All
          </button>
          {DEPTS.map((d) => (
            <button
              key={d}
              className={`corridor-view__filter-chip ${filterDept === d ? "corridor-view__filter-chip--active" : ""}`}
              onClick={() => setFilterDept(d)}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      <div className="corridor-view__layout">
        <div className="corridor-view__main">
          <section className="corridor-view__panel">
            <h2 className="corridor-view__panel-title">Corridor &mdash; JTJ to ED, 182 km</h2>
            {jobs ? (
              <CorridorStrip stations={stations} jobs={jobs} filterDept={filterDept} />
            ) : error ? (
              <ErrorState title="Could not load demand" detail={error} />
            ) : (
              <LoadingState label="Loading demand…" />
            )}
          </section>

          <section className="corridor-view__panel">
            <h2 className="corridor-view__panel-title">
              Maintenance demand {jobs ? `(${jobs.length} jobs)` : ""}
            </h2>
            {jobs && <DemandTable jobs={filterDept ? jobs.filter((j) => j.dept === filterDept) : jobs} />}
          </section>
        </div>

        <aside className="corridor-view__aside">
          <h2 className="corridor-view__panel-title">Geography</h2>
          <MapInset stations={stations} />
          <p className="corridor-view__aside-note">
            Southern Railway, Salem Division. Real station coordinates from
            published public data (DataMeet / Indian Railways, CC0).
          </p>
        </aside>
      </div>
    </div>
  );
}
