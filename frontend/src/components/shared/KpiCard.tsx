import type { ReactNode } from "react";
import "./KpiCard.css";

/**
 * One measured figure, with the unit and the caveat attached.
 *
 * `note` is not decoration. Several figures in this system are misleading on
 * their own -- asset availability most of all, since it is maximised by doing
 * no maintenance -- so the card is built to carry the qualifier in the same
 * visual unit as the number, not in a tooltip a judge will never open.
 *
 * `tone` is reserved for meaning. It is not applied automatically from the
 * value: nothing here knows whether a high number is good, and guessing would
 * paint the wrong thing green.
 */
export type KpiTone = "neutral" | "positive" | "caution" | "critical";

export function KpiCard({
  label,
  value,
  unit,
  note,
  tone = "neutral",
  emphasis = false,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  note?: ReactNode;
  tone?: KpiTone;
  emphasis?: boolean;
}) {
  return (
    <div
      className={`kpi kpi--${tone} ${emphasis ? "kpi--emphasis" : ""}`}
      data-testid="kpi-card"
    >
      <div className="kpi__label">{label}</div>
      <div className="kpi__value">
        {value}
        {unit ? <span className="kpi__unit">{unit}</span> : null}
      </div>
      {note ? <div className="kpi__note">{note}</div> : null}
    </div>
  );
}

/** A row of KPI cards that wraps rather than scrolls. */
export function KpiGrid({ children }: { children: ReactNode }) {
  return <div className="kpi-grid">{children}</div>;
}
