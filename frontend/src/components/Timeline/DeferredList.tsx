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
  if (deferred.length === 0) {
    return (
      <div className="deferred-list deferred-list--empty">
        Every job in this scenario was scheduled. Nothing was deferred.
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
