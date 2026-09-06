import "./StatusBadge.css";

export type Tone = "success" | "warning" | "error" | "info" | "neutral";

const LABEL: Record<string, { label: string; tone: Tone }> = {
  SCHEDULED: { label: "Scheduled", tone: "success" },
  OPTIMAL: { label: "Optimal", tone: "success" },
  FEASIBLE: { label: "Feasible (unproven)", tone: "warning" },
  DEFERRED: { label: "Deferred", tone: "neutral" },
  INFEASIBLE: { label: "Infeasible", tone: "error" },
  OUTBID: { label: "Outbid", tone: "warning" },
  INFEASIBLE_WHEN_FORCED: { label: "Infeasible when forced", tone: "error" },
};

/**
 * A small text-plus-mark status indicator. Colour is never the only signal:
 * every tone pairs with a distinct glyph and a text label, so the status
 * reads correctly for a colour-blind viewer or in greyscale print.
 */
export function StatusBadge({
  status,
  label,
}: {
  status: keyof typeof LABEL | string;
  label?: string;
}) {
  const entry = LABEL[status] ?? { label: label ?? status, tone: "neutral" as Tone };
  const text = label ?? entry.label;
  return (
    <span className={`status-badge status-badge--${entry.tone}`}>
      <span className="status-badge__mark" aria-hidden="true" />
      {text}
    </span>
  );
}
