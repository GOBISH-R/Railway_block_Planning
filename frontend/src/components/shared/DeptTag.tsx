import type { Dept } from "../../api/types";
import "./DeptTag.css";

const DEPT_LABEL: Record<Dept, string> = {
  ENGG: "Engineering",
  SNT: "Signal & Telecom",
  TRD: "Traction Distribution",
};

/** A small department identity chip: a coloured mark plus the short code. */
export function DeptTag({ dept, title }: { dept: Dept; title?: boolean }) {
  return (
    <span className={`dept-tag dept-tag--${dept}`} title={DEPT_LABEL[dept]}>
      <span className="dept-tag__swatch" aria-hidden="true" />
      {title ? DEPT_LABEL[dept] : dept}
    </span>
  );
}
