import type { DeferredEntry } from "../../api/types";
import { DeptTag } from "../shared/DeptTag";
import "./DeferredList.css";

/**
 * Deferred jobs have no time position by definition, so they are listed here
 * rather than plotted -- a block that does not exist cannot be drawn on a
 * timeline. This list is what makes deferral visible as an OUTPUT of the plan,
 * not a silent omission.
 */
export function DeferredList({
  deferred,
  onSelectJob,
}: {
  deferred: DeferredEntry[];
  onSelectJob: (jobId: string) => void;
}) {
  // `plan.deferred` is only readable once a plan exists -- TimelineView renders
  // this component under `{plan && ...}`, and shows its own loading and error
  // states instead when there is none. So an empty array here means the
  // optimiser deferred nothing, never that the data is missing or in flight.
  if (deferred.length === 0) {
    return (
      <div className="deferred-list">
        {/* Keeps the panel's heading rather than collapsing to a bare
            sentence, so an empty result still reads as this panel reporting
            zero rather than as a half-built column. */}
        <h2 className="deferred-list__title">Deferred (0)</h2>
        <p className="deferred-list__empty">
          <span className="deferred-list__empty-headline">No jobs deferred</span>
          {/* Attributed to the constraints, not the scenario: the same
              scenario defers a job at the default reliability floor and none
              at a lower one. */}
          All maintenance demand is scheduled within the current planning constraints.
        </p>
      </div>
    );
  }

  return (
    <div className="deferred-list">
      <h2 className="deferred-list__title">
        Deferred ({deferred.length})
        <span className="deferred-list__hint">Click a job to see why</span>
      </h2>
      <ul className="deferred-list__items">
        {deferred.map((d) => (
          <li key={d.job_id}>
            <button className="deferred-list__item" onClick={() => onSelectJob(d.job_id)}>
              <span className="deferred-list__job-id">{d.job_id}</span>
              <DeptTag dept={d.dept} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
