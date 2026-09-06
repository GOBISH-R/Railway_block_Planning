import type { JobExplanation } from "../../api/types";
import { DeptTag } from "../shared/DeptTag";
import { StatusBadge } from "../shared/StatusBadge";
import { EvidenceList, Section } from "./shared";
import "./JobExplanationView.css";

function formatMinutes(totalMinutes: number): string {
  const h = Math.floor(totalMinutes / 60) % 24;
  const m = totalMinutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

export function JobExplanationView({
  explanation,
  onSelectBlock,
}: {
  explanation: JobExplanation;
  onSelectBlock: (blockId: string) => void;
}) {
  const e = explanation;
  return (
    <>
      <div className="job-why__summary">
        <StatusBadge status={e.decision_status === "SCHEDULED" ? "SCHEDULED" : (e.verdict ?? "DEFERRED")} />
        <DeptTag dept={e.job.dept} title />
        <p className="job-why__activity">{e.job.activity}</p>
        <p className="job-why__meta">
          {e.job.section_id} &middot; {e.job.duration_mean_min.toFixed(0)}&plusmn;
          {e.job.duration_sd_min.toFixed(0)} min &middot; criticality {e.job.criticality.toFixed(2)}
        </p>
      </div>

      {e.decision_status === "SCHEDULED" ? (
        <ScheduledBody explanation={e} onSelectBlock={onSelectBlock} />
      ) : (
        <DeferredBody explanation={e} />
      )}

      <Section title="Evidence">
        <EvidenceList items={e.evidence} />
      </Section>
    </>
  );
}

function ScheduledBody({
  explanation: e,
  onSelectBlock,
}: {
  explanation: JobExplanation;
  onSelectBlock: (blockId: string) => void;
}) {
  const s = e.scheduled_in;
  if (!s) return null;
  return (
    <>
      <Section title="Scheduled in">
        <button className="job-why__block-link" onClick={() => onSelectBlock(s.block_id)}>
          Block {s.block_id} &middot; day {s.day} &middot; {s.length} min &middot; reliability{" "}
          {s.reliability.toFixed(2)}
        </button>
        {s.shares_block_with.length > 0 && (
          <p className="job-why__note">
            Shares the block with: {s.shares_block_with.join(", ")}
          </p>
        )}
      </Section>
      {e.caveat && <p className="job-why__caveat">{e.caveat}</p>}
    </>
  );
}

function DeferredBody({ explanation: e }: { explanation: JobExplanation }) {
  return (
    <Section title={e.verdict === "OUTBID" ? "Why it was outbid" : "Why it is infeasible"}>
      <p className="job-why__detail">{e.detail}</p>

      {e.verdict === "INFEASIBLE" && e.levers && (
        <table className="job-why__levers">
          <thead>
            <tr>
              <th scope="col">Lever tried</th>
              <th scope="col">Reliability</th>
              <th scope="col">Admissible?</th>
            </tr>
          </thead>
          <tbody>
            {e.levers.map((lever) => (
              <tr key={lever.lever}>
                <td>{lever.lever}</td>
                <td className="job-why__lever-value">
                  {lever.reliability != null ? lever.reliability.toFixed(3) : "—"}
                </td>
                <td>
                  {lever.reliability == null ? (
                    <span className="job-why__meets-no">No</span>
                  ) : lever.admissible ? (
                    <span className="job-why__meets-yes">Yes</span>
                  ) : (
                    <span className="job-why__meets-no">No</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {e.verdict === "OUTBID" && (
        <div className="job-why__outbid">
          <dl className="job-why__outbid-stats">
            <div>
              <dt>Price of forcing</dt>
              <dd>{e.price_of_forcing} wtm</dd>
            </div>
            <div>
              <dt>Candidate columns</dt>
              <dd>{e.candidate_columns}</dd>
            </div>
          </dl>
          {e.would_go_in && (
            <p className="job-why__note">
              Would go in: day {e.would_go_in.day}, {formatMinutes(e.would_go_in.start)}
              {" "}({e.would_go_in.length} min), reliability{" "}
              {e.would_go_in.reliability.toFixed(2)}
              {e.would_go_in.with.length > 0 && <> &middot; with {e.would_go_in.with.join(", ")}</>}
            </p>
          )}
          {e.newly_displaced && e.newly_displaced.length > 0 && (
            <p className="job-why__note">
              Would push out: {e.newly_displaced.join(", ")}
            </p>
          )}
        </div>
      )}
    </Section>
  );
}
