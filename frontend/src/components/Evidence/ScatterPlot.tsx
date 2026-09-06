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
  // Proportioned for the data rather than square-ish: five of the six methods
  // sit between 0.73 and 0.90 reliability while B3 sits near zero, so height
  // beyond what separates that cluster is empty gap. Wider and shorter than
  // before (was 420x320) gives the crowded x-axis more room and returns the
  // vertical space the gap was consuming, without touching either scale.
  const width = 480;
  const height = 300;
  const pad = { l: 46, r: 20, t: 18, b: 40 };

  // A square-root x-scale, not linear. One method (greedy-earliest) costs 4-6x
  // what the rest do, and on a linear scale that single outlier compresses
  // every other point -- including OURS and its closest baseline -- into a
  // sliver too narrow for their labels to fit without overlapping. sqrt
  // preserves ordering and the visual sense that B3 is far more expensive,
  // while giving the closely-priced methods enough room to read.
  const maxCost = Math.max(...points.map((p) => p.traffic_cost)) * 1.05;

  // The y-axis stays linear and is anchored at a true zero. Padding below the
  // lowest point used to push the domain to -0.02, which is not a reachable
  // reliability; clamping to 0 removes that dead band and lets the axis line
  // itself serve as the 0.0 gridline, giving B3 a labelled reference it
  // previously floated below. B3 is not moved, rescaled or de-emphasised --
  // it still reads as far below every other method.
  const minR = Math.max(0, Math.min(...points.map((p) => p.min_reliability)) - 0.05);
  const maxR = 1.0;

  const x = (cost: number) =>
    pad.l + (Math.sqrt(cost) / Math.sqrt(maxCost)) * (width - pad.l - pad.r);
  const y = (r: number) => height - pad.b - ((r - minR) / (maxR - minR)) * (height - pad.t - pad.b);

  const isOurs = (m: string) => m.toUpperCase() === "OURS";
  const radius = (m: string) => (isOurs(m) ? 6 : 4.5);

  const placed = points.map((p) => ({
    ...p,
    px: x(p.traffic_cost),
    py: y(p.min_reliability),
  }));

  /**
   * Labels sit to the right of their point, except where the point immediately
   * to the right shares the same row -- then this one's label goes left, so
   * the pair opens outwards instead of the left label running into the right
   * point's marker.
   *
   * This replaces an alternating above/below stagger that keyed off cost rank.
   * OURS and B1 both have min_reliability 0.90, so they share a y exactly, and
   * their ranks happened to give them the same offset too: the "OURS" label
   * started 8px right of its own marker and ran into B1's, 33px away. Ranking
   * could not see that; proximity can.
   */
  const SAME_ROW_PX = 6;
  const LABEL_CLEARANCE_PX = 34;
  const labelSide = new Map<string, 1 | -1>();
  for (const p of placed) {
    const crowdedOnTheRight = placed.some(
      (q) =>
        q.method !== p.method &&
        Math.abs(q.py - p.py) < SAME_ROW_PX &&
        q.px > p.px &&
        q.px - p.px < LABEL_CLEARANCE_PX
    );
    labelSide.set(p.method, crowdedOnTheRight ? -1 : 1);
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="scatter-plot" role="img"
         aria-label="Scatter plot of traffic cost against minimum reliability, one point per method">
      {/* axes */}
      <line x1={pad.l} x2={pad.l} y1={pad.t} y2={height - pad.b} className="scatter-plot__axis" />
      <line x1={pad.l} x2={width - pad.r} y1={height - pad.b} y2={height - pad.b} className="scatter-plot__axis" />

      {[0, 0.2, 0.4, 0.6, 0.8, 1.0].filter((v) => v >= minR).map((v) => (
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

      {placed.map((p) => {
        const side = labelSide.get(p.method) ?? 1;
        const r = radius(p.method);
        return (
          <g key={p.method}>
            <circle
              cx={p.px}
              cy={p.py}
              r={r}
              className={isOurs(p.method) ? "scatter-plot__point scatter-plot__point--ours" : "scatter-plot__point"}
            />
            <text
              x={p.px + side * (r + 4)}
              y={p.py + 3}
              textAnchor={side === 1 ? "start" : "end"}
              className="scatter-plot__label"
            >
              {p.method}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
