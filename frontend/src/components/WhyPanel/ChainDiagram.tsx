import type { DepartmentalChain } from "../../api/types";
import "./ChainDiagram.css";

const DEPT_VAR: Record<string, string> = {
  ENGG: "var(--dept-engg)",
  SNT: "var(--dept-snt)",
  TRD: "var(--dept-trd)",
};

/**
 * The project's central diagram: each department's hand-back chain drawn to
 * scale against the block envelope, so "the block ends at the maximum of
 * three independent chains" is a picture rather than a sentence.
 *
 * A chain's bar spans mean +/- 1 sd; the vertical line is the selected block
 * length. A chain crossing the line is the one at risk of a late hand-back.
 */
export function ChainDiagram({
  chains,
  blockLength,
}: {
  chains: DepartmentalChain[];
  blockLength: number;
}) {
  const width = 360;
  const rowHeight = 40;
  const height = chains.length * rowHeight + 24;
  const maxExtent = Math.max(blockLength, ...chains.map((c) => c.mean_min + 2 * c.sd_min)) * 1.05;
  const scale = (minutes: number) => (minutes / maxExtent) * (width - 8);

  const binding = chains.reduce((a, b) => (b.mean_min > a.mean_min ? b : a), chains[0]);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="chain-diagram"
      role="img"
      aria-label={`Departmental hand-back chains against a ${blockLength}-minute block. ${binding.dept} has the longest chain at ${binding.mean_min.toFixed(0)} minutes.`}
    >
      <line
        x1={scale(blockLength)}
        x2={scale(blockLength)}
        y1={0}
        y2={height - 16}
        className="chain-diagram__envelope"
      />
      <text x={scale(blockLength)} y={height - 4} className="chain-diagram__envelope-label" textAnchor="middle">
        {blockLength} min envelope
      </text>

      {chains.map((chain, i) => {
        const y = i * rowHeight + 8;
        const barX = scale(Math.max(0, chain.mean_min - chain.sd_min));
        const barW = scale(chain.mean_min + chain.sd_min) - barX;
        const meanX = scale(chain.mean_min);
        const isBinding = chain.dept === binding.dept;
        return (
          <g key={chain.dept}>
            <text x={0} y={y + 4} className="chain-diagram__dept-label">
              {chain.dept}
            </text>
            <rect
              x={barX + 30}
              y={y - 5}
              width={Math.max(2, barW)}
              height={10}
              rx={2}
              fill={DEPT_VAR[chain.dept] ?? "var(--ink-2)"}
              opacity={isBinding ? 1 : 0.55}
            />
            <line
              x1={meanX + 30}
              x2={meanX + 30}
              y1={y - 8}
              y2={y + 8}
              className="chain-diagram__mean-tick"
            />
            <text x={width - 4} y={y + 4} className="chain-diagram__phi-label" textAnchor="end">
              &Phi;={chain.phi.toFixed(2)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
