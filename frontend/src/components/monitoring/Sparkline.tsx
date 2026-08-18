import type { Observation } from "../../types/monitoring";

/**
 * A vital's recent history as a bare polyline.
 *
 * Hand-rolled SVG rather than a charting library: the whole shape is forty
 * lines, and a dependency would bring a visual language that fights the rest of
 * the interface. The line carries movement; the number beside it carries value.
 *
 * The trace draws itself on arrival — the one flourish it gets, and it is
 * reporting something real: this window was just plotted. The head of the trace
 * is marked because "where the patient is now" is the point a reader looks for.
 *
 * A series too short to mean anything renders as a hatched band, not a flat
 * line — the same rule the RangeBar follows for UNKNOWN.
 */

interface Props {
  observations: Observation[];
  width?: number;
  height?: number;
}

export function Sparkline({ observations, width = 132, height = 34 }: Props) {
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

  const coords = values.map((v, i) => [x(i), y(v)] as const);
  const points = coords.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join(" ");

  // Length of the drawn path, so the reveal runs at the same rate whatever the
  // shape of the trace.
  const length = coords.reduce((total, [px, py], i) => {
    if (i === 0) return 0;
    const [qx, qy] = coords[i - 1];
    return total + Math.hypot(px - qx, py - qy);
  }, 0);

  const last = values[values.length - 1];
  const [headX, headY] = coords[coords.length - 1];

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${values.length} readings, latest ${last}`}
      className="overflow-visible text-ink"
    >
      {/* Baseline: the patient's own first reading, so the trace has something
          to be above or below. */}
      <line
        x1="0"
        y1={y(values[0])}
        x2={width}
        y2={y(values[0])}
        stroke="var(--color-rule)"
        strokeWidth="1"
        strokeDasharray="2 3"
      />
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        className="animate-draw"
        style={{ "--draw-length": length.toFixed(0) } as React.CSSProperties}
      />
      <circle
        cx={headX}
        cy={headY}
        r="2.75"
        fill="var(--color-panel)"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}
