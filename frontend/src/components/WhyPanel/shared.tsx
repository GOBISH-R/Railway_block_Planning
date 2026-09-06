import type { Evidence, MandatoryPairing } from "../../api/types";
import "./shared.css";

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="why-section">
      <h3 className="why-section__title">{title}</h3>
      {children}
    </section>
  );
}

export function EvidenceList({ items }: { items: Evidence[] }) {
  return (
    <ul className="evidence-list">
      {items.map((e) => (
        <li key={e.code} className="evidence-list__item">
          <p className="evidence-list__statement">{e.statement}</p>
          <p className="evidence-list__source">
            {e.source} <ProvenanceTag code={e.provenance} />
          </p>
        </li>
      ))}
    </ul>
  );
}

const PROVENANCE_LABEL: Record<string, string> = {
  A_REAL: "real data",
  B_DERIVED: "derived",
  C_RULE: "railway rule",
  D_SYNTHETIC: "synthetic",
  E_ASSUMPTION: "declared assumption",
};

export function ProvenanceTag({ code }: { code: string }) {
  return <span className="provenance-tag">{PROVENANCE_LABEL[code] ?? code}</span>;
}

export function PairingsList({ items }: { items: MandatoryPairing[] }) {
  if (items.length === 0) {
    return <p className="why-empty">No rule-mandated companion work in this block.</p>;
  }
  return (
    <ul className="pairings-list">
      {items.map((p) => (
        <li key={p.companion_job_id} className="pairings-list__item">
          <p>
            <strong>{p.parent_activity}</strong> compels <strong>{p.compelled_dept}</strong> to
            perform <strong>{p.companion_activity}</strong>
            {p.must_follow_parent ? " immediately after it" : " in the same block"}.
          </p>
          <p className="pairings-list__source">{p.source}</p>
        </li>
      ))}
    </ul>
  );
}
