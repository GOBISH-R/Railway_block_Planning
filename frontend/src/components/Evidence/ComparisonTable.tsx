import "./ComparisonTable.css";

export interface ColumnDef {
  key: string;
  label: string;
  format?: (value: number | string) => string;
  numeric?: boolean;
}

/**
 * A plain, dense table -- the memory document's own instruction for the
 * Evidence view ("Plain HTML tables... no rounding invented in the frontend").
 * Every value here is passed straight through from /comparison; this
 * component only selects and labels columns, it does not compute anything.
 */
export function ComparisonTable({
  rows,
  columns,
  highlightMethod,
}: {
  rows: Array<Record<string, number | string>>;
  columns: ColumnDef[];
  highlightMethod?: string;
}) {
  return (
    <div className="comparison-table__scroll">
      <table className="comparison-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.numeric ? "comparison-table__num" : undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const methodValue = String(row.method ?? row.scenario ?? i);
            const isHighlighted = highlightMethod != null && methodValue.startsWith(highlightMethod);
            return (
              <tr key={methodValue + i} className={isHighlighted ? "comparison-table__row--highlight" : undefined}>
                {columns.map((c) => {
                  const raw = row[c.key];
                  return (
                    <td key={c.key} className={c.numeric ? "comparison-table__num" : undefined}>
                      {c.format && raw != null ? c.format(raw) : String(raw ?? "—")}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
