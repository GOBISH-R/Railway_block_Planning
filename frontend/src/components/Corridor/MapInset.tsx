import type { StationPoint } from "./corridorProfile";
import "./MapInset.css";

/**
 * A small true-geometry map, drawn as SVG straight from the stations' own
 * lat/lon -- no tile server, so it works fully offline. Purpose is context
 * ("this is a real place"), not navigation, per the project's brief; the
 * linear strip above is the one that carries planning meaning.
 */
export function MapInset({ stations }: { stations: StationPoint[] }) {
  const width = 220;
  const height = 160;
  const pad = 14;

  const lats = stations.map((s) => s.latitude);
  const lons = stations.map((s) => s.longitude);
  const latMin = Math.min(...lats);
  const latMax = Math.max(...lats);
  const lonMin = Math.min(...lons);
  const lonMax = Math.max(...lons);

  // Equirectangular is adequate at this scale (~1.8 degrees of latitude);
  // longitude is compressed by cos(latitude) so the shape is not stretched.
  const midLatRad = ((latMin + latMax) / 2) * (Math.PI / 180);
  const lonScale = Math.cos(midLatRad);

  const spanX = (lonMax - lonMin) * lonScale || 1;
  const spanY = latMax - latMin || 1;
  const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanY);

  const project = (lat: number, lon: number) => {
    const x = pad + ((lon - lonMin) * lonScale) * scale;
    const y = height - pad - (lat - latMin) * scale;
    return [x, y] as const;
  };

  const path = stations.map((s) => project(s.latitude, s.longitude));

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="map-inset"
      role="img"
      aria-label="Map of the corridor's real geography, Jolarpettai to Erode"
    >
      <polyline
        points={path.map(([x, y]) => `${x},${y}`).join(" ")}
        fill="none"
        className="map-inset__route"
      />
      {stations.map((s, i) => {
        const [x, y] = path[i];
        return (
          <circle
            key={s.station_code}
            cx={x}
            cy={y}
            r={s.is_junction ? 3 : 1.6}
            className={s.is_junction ? "map-inset__station map-inset__station--junction" : "map-inset__station"}
          />
        );
      })}
      {[0, stations.length - 1].map((i) => {
        const [x, y] = path[i];
        return (
          <text key={i} x={x} y={y - 6} textAnchor="middle" className="map-inset__label">
            {stations[i].station_code}
          </text>
        );
      })}
    </svg>
  );
}
