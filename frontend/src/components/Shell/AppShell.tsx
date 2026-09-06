import type { ReactNode } from "react";
import "./AppShell.css";

export type ViewKey = "timeline" | "corridor" | "evidence";

const NAV: Array<{ key: ViewKey; label: string; hint: string }> = [
  { key: "timeline", label: "Plan", hint: "The recommended plan for the selected scenario" },
  { key: "corridor", label: "Corridor & Demand", hint: "The line, and what work is waiting on it" },
  { key: "evidence", label: "Evidence", hint: "How this method compares against baselines" },
];

export function AppShell({
  active,
  onNavigate,
  headerRight,
  children,
}: {
  active: ViewKey;
  onNavigate: (view: ViewKey) => void;
  headerRight?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="shell">
      <header className="shell__header">
        <div className="shell__brand">
          <span className="shell__brand-mark" aria-hidden="true" />
          <div>
            <div className="shell__brand-name">BlockPlan</div>
            <div className="shell__brand-sub">Jolarpettai &ndash; Salem &ndash; Erode corridor</div>
          </div>
        </div>

        <nav className="shell__nav" aria-label="Primary">
          {NAV.map((item) => (
            <button
              key={item.key}
              className={`shell__nav-item ${active === item.key ? "shell__nav-item--active" : ""}`}
              onClick={() => onNavigate(item.key)}
              aria-current={active === item.key ? "page" : undefined}
              title={item.hint}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="shell__header-right">{headerRight}</div>
      </header>

      <main className="shell__main">{children}</main>
    </div>
  );
}
