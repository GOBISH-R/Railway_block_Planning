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

  // Reserved space either side of the plot. Previously the plot ran the full
  // width and the two gutters were improvised at the point of use -- bars added
  // +30 for the department label while the envelope line did not, so the line
  // sat 30 units left of the bars it is meant to be compared against, and the
  // right-anchored phi labels overprinted it. Both gutters are now declared
  // once and every x goes through `x()`, so the frames cannot drift apart.
  const LABEL_GUTTER = 30; // left: "ENGG" at 10px bold
  const PHI_GUTTER = 58; // right: "Phi=0.00" at 9px mono
  const plotWidth = width - LABEL_GUTTER - PHI_GUTTER;
  const x = (minutes: number) => LABEL_GUTTER + (minutes / maxExtent) * plotWidth;

  const binding = chains.reduce((a, b) => (b.mean_min > a.mean_min ? b : a), chains[0]);

  // The envelope label is centred on its line, so it overhangs by half its
  // width and used to be clipped by the viewBox when the block filled the
  // scale. Estimated at ~4.6px per character for the 9px face, then clamped
  // to keep both ends inside the viewBox.
  const envelopeLabel = `${blockLength} min envelope`;
  const envelopeLabelHalf = Math.min((envelopeLabel.length * 4.6) / 2, width / 2);
  const envelopeLabelX = Math.min(
    Math.max(x(blockLength), envelopeLabelHalf),
    width - envelopeLabelHalf
  );

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="chain-diagram"
      role="img"
      aria-label={`Departmental hand-back chains against a ${blockLength}-minute block. ${binding.dept} has the longest chain at ${binding.mean_min.toFixed(0)} minutes.`}
    >
      <line
        x1={x(blockLength)}
        x2={x(blockLength)}
        y1={0}
        y2={height - 16}
        className="chain-diagram__envelope"
      />
      <text
        x={envelopeLabelX}
        y={height - 4}
        className="chain-diagram__envelope-label"
        textAnchor="middle"
      >
        {envelopeLabel}
      </text>

      {chains.map((chain, i) => {
        const y = i * rowHeight + 8;
        const barX = x(Math.max(0, chain.mean_min - chain.sd_min));
        const barW = x(chain.mean_min + chain.sd_min) - barX;
        const meanX = x(chain.mean_min);
        const isBinding = chain.dept === binding.dept;
        return (
          <g key={chain.dept}>
            <text x={0} y={y + 4} className="chain-diagram__dept-label">
              {chain.dept}
            </text>
            <rect
              x={barX}
              y={y - 5}
              width={Math.max(2, barW)}
              height={10}
              rx={2}
              fill={DEPT_VAR[chain.dept] ?? "var(--ink-2)"}
              opacity={isBinding ? 1 : 0.55}
            />
            <line
              x1={meanX}
              x2={meanX}
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
