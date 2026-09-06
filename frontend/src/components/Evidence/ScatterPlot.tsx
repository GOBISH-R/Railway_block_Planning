import "./ScatterPlot.css";

interface Point {
  method: string;
  traffic_cost: number;
  min_reliability: number;
}

/**
 * One scatter, six labelled points: traffic cost against minimum reliability
 * per method. This is the plot the project's own evidence view calls for --
 * one is enough, and it answers a specific question (is reliability bought at
 * a traffic-cost price, and by how much) rather than filling space.
 */
export function ScatterPlot({ points }: { points: Point[] }) {
  const width = 420;
  const height = 320;
  const pad = { l: 46, r: 16, t: 16, b: 40 };

  // A square-root x-scale, not linear. One method (greedy-earliest) costs 4-6x
  // what the rest do, and on a linear scale that single outlier compresses
  // every other point -- including OURS and its closest baseline -- into a
  // sliver too narrow for their labels to fit without overlapping. sqrt
  // preserves ordering and the visual sense that B3 is far more expensive,
  // while giving the closely-priced methods enough room to read.
  const maxCost = Math.max(...points.map((p) => p.traffic_cost)) * 1.05;
  const minR = Math.min(...points.map((p) => p.min_reliability)) - 0.05;
  const maxR = 1.0;

  const x = (cost: number) =>
    pad.l + (Math.sqrt(cost) / Math.sqrt(maxCost)) * (width - pad.l - pad.r);
  const y = (r: number) => height - pad.b - ((r - minR) / (maxR - minR)) * (height - pad.t - pad.b);

  const isOurs = (m: string) => m.toUpperCase() === "OURS";

  // Stagger labels above/below their point in cost order, so two points close
  // enough to sit at nearly the same x do not print overlapping text.
  const labelDy = new Map<string, number>();
  [...points]
    .sort((a, b) => a.traffic_cost - b.traffic_cost)
    .forEach((p, i) => labelDy.set(p.method, i % 2 === 0 ? 4 : -8));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="scatter-plot" role="img"
         aria-label="Scatter plot of traffic cost against minimum reliability, one point per method">
      {/* axes */}
      <line x1={pad.l} x2={pad.l} y1={pad.t} y2={height - pad.b} className="scatter-plot__axis" />
      <line x1={pad.l} x2={width - pad.r} y1={height - pad.b} y2={height - pad.b} className="scatter-plot__axis" />

      {[0.2, 0.4, 0.6, 0.8, 1.0].filter((v) => v >= minR).map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={width - pad.r} y1={y(v)} y2={y(v)} className="scatter-plot__grid" />
          <text x={pad.l - 6} y={y(v) + 3} textAnchor="end" className="scatter-plot__tick">
            {v.toFixed(1)}
          </text>
        </g>
      ))}
      {Array.from({ length: 5 }, (_, i) => (maxCost / 4) * i).map((v) => (
        <text key={v} x={x(v)} y={height - pad.b + 14} textAnchor="middle" className="scatter-plot__tick">
          {v.toFixed(0)}
        </text>
      ))}

      <text x={pad.l} y={12} className="scatter-plot__axis-label">min reliability</text>
      <text x={width - pad.r} y={height - 6} textAnchor="end" className="scatter-plot__axis-label">
        traffic cost (weighted train-min)
      </text>

      {points.map((p) => (
        <g key={p.method}>
          <circle
            cx={x(p.traffic_cost)}
            cy={y(p.min_reliability)}
            r={isOurs(p.method) ? 6 : 4.5}
            className={isOurs(p.method) ? "scatter-plot__point scatter-plot__point--ours" : "scatter-plot__point"}
          />
          <text
            x={x(p.traffic_cost) + 8}
            y={y(p.min_reliability) + (labelDy.get(p.method) ?? 3)}
            className="scatter-plot__label"
          >
            {p.method}
          </text>
        </g>
      ))}
    </svg>
  );
}
