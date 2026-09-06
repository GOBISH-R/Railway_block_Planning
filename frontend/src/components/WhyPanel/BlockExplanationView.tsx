import type { BlockExplanation } from "../../api/types";
import { DeptTag } from "../shared/DeptTag";
import { StatusBadge } from "../shared/StatusBadge";
import { ChainDiagram } from "./ChainDiagram";
import { EvidenceList, PairingsList, Section } from "./shared";
import "./BlockExplanationView.css";

export function BlockExplanationView({
  explanation,
  onSelectJob,
}: {
  explanation: BlockExplanation;
  onSelectJob: (jobId: string) => void;
}) {
  const e = explanation;
  return (
    <>
      <div className="block-why__summary">
        <StatusBadge status="SCHEDULED" />
        <p className="block-why__location">
          {e.section.from_station_code} &rarr; {e.section.to_station_code}
          <span className="block-why__line"> ({e.section.line})</span>
        </p>
        <p className="block-why__time">
          Day {e.day} &middot; {formatMinutes(e.start_min)}&ndash;{formatMinutes(e.end_min)}
          <span className="block-why__length"> ({e.length} min)</span>
        </p>
      </div>

      <Section title="Hand-back reliability">
        <ChainDiagram chains={e.departmental_chains} blockLength={e.length} />
        <p className="block-why__reliability-line">
          Modelled P(hand back within {e.length} min) ={" "}
          <strong>{e.reliability.toFixed(3)}</strong>, against the policy floor{" "}
          &theta; = {e.constraints.applied_theta}. The block ends at the maximum of the{" "}
          {e.departmental_chains.length} independent department chains above.
        </p>
        <ReliabilityByLength values={e.reliability_by_allowed_length} theta={e.constraints.applied_theta} />
      </Section>

      <Section title={`Jobs in this block (${e.jobs.length})`}>
        <ul className="block-why__jobs">
          {e.jobs.map((job) => (
            <li key={job.job_id}>
              <button className="block-why__job" onClick={() => onSelectJob(job.job_id)}>
                <span className="block-why__job-id">{job.job_id}</span>
                <DeptTag dept={job.dept} />
                <span className="block-why__job-activity">{job.activity}</span>
                <span className="block-why__job-duration">{job.duration_mean_min.toFixed(0)} min</span>
              </button>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Rule-mandated companion work">
        <PairingsList items={e.constraints.mandatory_pairings} />
      </Section>

      <Section title="Objective">
        <dl className="block-why__objective">
          <div>
            <dt>Traffic cost</dt>
            <dd>{e.objective.traffic_cost.toFixed(1)}</dd>
          </div>
          <div>
            <dt>Expected overrun</dt>
            <dd>{e.objective.expected_overrun_cost.toFixed(1)}</dd>
          </div>
          <div>
            <dt>Column total</dt>
            <dd>{e.objective.column_total_cost.toFixed(1)}</dd>
          </div>
        </dl>
        <p className="block-why__units">{e.objective.units}</p>
      </Section>

      <Section title="Evidence">
        <EvidenceList items={e.evidence} />
      </Section>

      <p className="block-why__provenance-notice">{e.provenance.notice}</p>
    </>
  );
}

function ReliabilityByLength({
  values,
  theta,
}: {
  values: Record<string, number>;
  theta: number;
}) {
  const entries = Object.entries(values).sort((a, b) => Number(a[0]) - Number(b[0]));
  return (
    <table className="block-why__envelope-table">
      <thead>
        <tr>
          <th scope="col">Length</th>
          <th scope="col">Reliability</th>
          <th scope="col">Meets &theta;?</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([length, reliability]) => (
          <tr key={length}>
            <td>{length} min</td>
            <td className="block-why__envelope-value">{reliability.toFixed(3)}</td>
            <td>
              {reliability >= theta ? (
                <span className="block-why__meets-yes">Yes</span>
              ) : (
                <span className="block-why__meets-no">No</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function formatMinutes(totalMinutes: number): string {
  const h = Math.floor(totalMinutes / 60) % 24;
  const m = totalMinutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}
