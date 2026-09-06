import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { ComparisonResponse } from "../../api/types";
import { ErrorState, LoadingState } from "../shared/ViewStates";
import { ComparisonTable, type ColumnDef } from "./ComparisonTable";
import { ScatterPlot } from "./ScatterPlot";
import "./EvidenceView.css";

const fixed1 = (v: number | string) => Number(v).toFixed(1);
const fixed2 = (v: number | string) => Number(v).toFixed(2);
const pct0 = (v: number | string) => `${(Number(v) * 100).toFixed(0)}%`;

const METHOD_COLUMNS: ColumnDef[] = [
  { key: "method", label: "Method" },
  { key: "blocks", label: "Blocks", numeric: true },
  { key: "jobs_done", label: "Done", numeric: true },
  { key: "jobs_deferred", label: "Deferred", numeric: true },
  { key: "traffic_cost", label: "Traffic cost", numeric: true, format: fixed1 },
  { key: "exp_overrun_cost", label: "Exp. overrun", numeric: true, format: fixed1 },
  { key: "cross_dept_share", label: "Cross-dept", numeric: true, format: pct0 },
  { key: "mean_reliability", label: "Mean R", numeric: true, format: fixed2 },
  { key: "min_reliability", label: "Min R", numeric: true, format: fixed2 },
];

const SCORING_COLUMNS: ColumnDef[] = [
  { key: "method", label: "Method" },
  { key: "realisations", label: "Realisations", numeric: true },
  { key: "plan_observed_rate_with_penalty", label: "Observed on-time", numeric: true, format: pct0 },
  { key: "worst_block_observed_with_penalty", label: "Worst block", numeric: true, format: fixed2 },
  { key: "max_observed_overrun_min_with_penalty", label: "Max overrun (min)", numeric: true, format: fixed1 },
  { key: "mean_abs_error_with_penalty", label: "Mean |error|", numeric: true, format: (v) => Number(v).toFixed(3) },
];

const SCENARIO_COLUMNS: ColumnDef[] = [
  { key: "scenario", label: "Scenario" },
  { key: "status", label: "Status" },
  { key: "jobs_after_pairing", label: "Jobs", numeric: true },
  { key: "blocks", label: "Blocks", numeric: true },
  { key: "deferred", label: "Deferred", numeric: true },
  { key: "cross_department_pct", label: "Cross-dept", numeric: true, format: pct0 },
  { key: "traffic_cost", label: "Traffic cost", numeric: true, format: fixed1 },
  { key: "avg_reliability", label: "Avg R", numeric: true, format: fixed2 },
  { key: "min_reliability", label: "Min R", numeric: true, format: fixed2 },
];

export function EvidenceView() {
  const [data, setData] = useState<ComparisonResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .comparison()
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the evidence data."));
  }, []);

  if (error) return <ErrorState title="Could not load evidence" detail={error} />;
  if (!data) return <LoadingState label="Loading evidence…" />;

  const scatterPoints = data.method_comparison.map((r) => ({
    method: String(r.method).split(" ")[0],
    traffic_cost: Number(r.traffic_cost),
    min_reliability: Number(r.min_reliability),
  }));

  return (
    <div className="evidence-view">
      <section className="evidence-view__panel">
        <h2 className="evidence-view__title">Method comparison</h2>
        <p className="evidence-view__caption">
          Six methods on the identical NORMAL_TRAFFIC instance. Numbers match{" "}
          <code>method_comparison.csv</code> exactly &mdash; this is a reader, not a runner.
        </p>
        <ComparisonTable rows={data.method_comparison} columns={METHOD_COLUMNS} highlightMethod="OURS" />
      </section>

      <div className="evidence-view__row">
        <section className="evidence-view__panel evidence-view__panel--half">
          <h2 className="evidence-view__title">Traffic cost vs. minimum reliability</h2>
          <p className="evidence-view__caption">
            Is reliability bought at a traffic-cost price, and how much?
          </p>
          <ScatterPlot points={scatterPoints} />
        </section>

        <section className="evidence-view__panel evidence-view__panel--half">
          <h2 className="evidence-view__title">Execution scoring (30 independent realisations)</h2>
          <p className="evidence-view__caption">
            The worst block matters more than the average &mdash; one late hand-back delays
            the morning services however well the rest behaved.
          </p>
          <ComparisonTable rows={data.execution_scoring_summary} columns={SCORING_COLUMNS} highlightMethod="OURS" />
        </section>
      </div>

      <section className="evidence-view__panel">
        <h2 className="evidence-view__title">Scenario benchmark</h2>
        <p className="evidence-view__caption">All eight scenarios, generated (not cloned), all solved to proven optimality.</p>
        <ComparisonTable rows={data.benchmark_results} columns={SCENARIO_COLUMNS} />
      </section>

      <p className="evidence-view__notice">
        Infrastructure, stations and train schedules are real public data. Maintenance
        jobs, block requests and execution realisations are synthetic. This is a
        reproducible synthetic benchmark, not Indian Railways maintenance data.
      </p>
    </div>
  );
}
