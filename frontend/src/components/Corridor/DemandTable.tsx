import { useMemo, useState } from "react";
import type { DemandJob } from "../../api/types";
import { DeptTag } from "../shared/DeptTag";
import "./DemandTable.css";

type SortKey = "due_day" | "criticality" | "duration_mean_min";

export function DemandTable({ jobs }: { jobs: DemandJob[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("due_day");
  const [sortDesc, setSortDesc] = useState(false);

  const sorted = useMemo(() => {
    const copy = [...jobs];
    copy.sort((a, b) => (sortDesc ? b[sortKey] - a[sortKey] : a[sortKey] - b[sortKey]));
    return copy;
  }, [jobs, sortKey, sortDesc]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDesc((d) => !d);
    } else {
      setSortKey(key);
      setSortDesc(false);
    }
  };

  return (
    <div className="demand-table__scroll">
      <table className="demand-table">
        <thead>
          <tr>
            <th scope="col">Job</th>
            <th scope="col">Dept</th>
            <th scope="col">Activity</th>
            <th scope="col">Section</th>
            <SortableHeader label="Duration" active={sortKey === "duration_mean_min"} desc={sortDesc} onClick={() => onSort("duration_mean_min")} />
            <SortableHeader label="Due day" active={sortKey === "due_day"} desc={sortDesc} onClick={() => onSort("due_day")} />
            <SortableHeader label="Criticality" active={sortKey === "criticality"} desc={sortDesc} onClick={() => onSort("criticality")} />
            <th scope="col">Priority</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((job) => (
            <tr key={job.job_id}>
              <td className="demand-table__mono">{job.job_id}</td>
              <td><DeptTag dept={job.dept} /></td>
              <td>{job.activity}</td>
              <td className="demand-table__mono">{job.section_id}</td>
              <td className="demand-table__num">{job.duration_mean_min.toFixed(0)} min</td>
              <td className="demand-table__num">{job.due_day}</td>
              <td className="demand-table__num">{job.criticality.toFixed(2)}</td>
              <td>{job.priority}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SortableHeader({
  label,
  active,
  desc,
  onClick,
}: {
  label: string;
  active: boolean;
  desc: boolean;
  onClick: () => void;
}) {
  return (
    <th scope="col" aria-sort={active ? (desc ? "descending" : "ascending") : "none"}>
      <button className="demand-table__sort" onClick={onClick}>
        {label}
        {active && <span aria-hidden="true">{desc ? " ↓" : " ↑"}</span>}
      </button>
    </th>
  );
}
