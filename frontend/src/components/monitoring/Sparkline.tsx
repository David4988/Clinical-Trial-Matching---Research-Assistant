import type { Observation } from "../../types/monitoring";

/**
 * A vital's recent history as a bare polyline.
 *
 * Hand-rolled SVG rather than a charting library: the whole shape is twenty
 * lines, and a dependency would bring a visual language that fights the rest of
 * the interface. The line carries movement; the number beside it carries value.
 *
 * A series too short to mean anything renders as a hatched band, not a flat
 * line — the same rule the RangeBar follows for UNKNOWN.
 */

interface Props {
  observations: Observation[];
  width?: number;
  height?: number;
}

export function Sparkline({ observations, width = 120, height = 28 }: Props) {
  if (observations.length < 2) {
    return (
      <div
        className="hatch border border-rule"
        style={{ width, height }}
        role="img"
        aria-label="Not enough readings to plot"
      />
    );
  }

  const values = observations.map((o) => o.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  // Inset by a pixel so the stroke is not clipped at the extremes.
  const x = (i: number) => (i / (values.length - 1)) * (width - 2) + 1;
  const y = (v: number) => height - 1 - ((v - min) / span) * (height - 2);

  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const last = values[values.length - 1];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${values.length} readings, latest ${last}`}
      className="overflow-visible"
    >
      <polyline
        points={points}
        fill="none"
        stroke="var(--color-ink)"
        strokeWidth="1.25"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={x(values.length - 1)} cy={y(last)} r="2" fill="var(--color-ink)" />
    </svg>
  );
}
