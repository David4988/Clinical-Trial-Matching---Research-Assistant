import { useEffect, useMemo, useRef, useState } from "react";
import type {
  DoseAdministration,
  Intervention,
  MeasurementType,
  Observation,
  RiskLevel,
  RiskTransition,
} from "../../types/monitoring";

/**
 * The monitoring strip: every vital on one time axis, with the events that
 * happened to this participant drawn through them.
 *
 * Six separate sparklines could show that a number moved. Only this can show
 * that it moved *after the dose*, that the protocol intervened *at that point*,
 * and that the risk band changed *there* — which is the entire clinical
 * argument the product makes. So the lanes share one x-scale, and doses,
 * interventions and the risk transition are drawn as rules straight through
 * them.
 *
 * Hand-rolled SVG. A charting library would bring its own visual language and
 * would still need this much custom work to place clinical events.
 */

const ORDER: MeasurementType[] = [
  "SYSTOLIC_BP",
  "DIASTOLIC_BP",
  "HEART_RATE",
  "RESPIRATORY_RATE",
  "SPO2",
  "TEMPERATURE",
];

const SHORT: Record<string, string> = {
  SYSTOLIC_BP: "SBP",
  DIASTOLIC_BP: "DBP",
  HEART_RATE: "HR",
  RESPIRATORY_RATE: "RR",
  SPO2: "SpO₂",
  TEMPERATURE: "Temp",
};

const RISK_FILL: Record<RiskLevel, string> = {
  GREEN: "var(--color-safe)",
  AMBER: "var(--color-caution)",
  RED: "var(--color-alert)",
  UNKNOWN: "var(--color-rule-strong)",
};

const GUTTER_WIDE = 96;
const GUTTER_NARROW = 52;
const RIGHT_WIDE = 64;
const RIGHT_NARROW = 34;
const RIBBON = 22;
const LANE = 64;
const AXIS = 24;

interface Props {
  observations: Observation[];
  doses: DoseAdministration[];
  interventions: Intervention[];
  transition: RiskTransition | null;
  riskLevel: RiskLevel;
}

export function TrajectoryChart({
  observations,
  doses,
  interventions,
  transition,
  riskLevel,
}: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [hoverX, setHoverX] = useState<number | null>(null);

  useEffect(() => {
    const element = wrap.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      // Never wider than the space available: the page must not scroll
      // sideways because of this chart.
      setWidth(Math.max(300, entry.contentRect.width));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const lanes = useMemo(() => {
    const byType = new Map<string, Observation[]>();
    for (const observation of observations) {
      const list = byType.get(observation.measurement_type) ?? [];
      list.push(observation);
      byType.set(observation.measurement_type, list);
    }
    return ORDER.filter((type) => (byType.get(type) ?? []).length > 0).map((type) => {
      const series = [...(byType.get(type) ?? [])].sort(
        (a, b) => +new Date(a.recorded_at) - +new Date(b.recorded_at),
      );
      const values = series.map((o) => o.value);
      return {
        type,
        series,
        min: Math.min(...values),
        max: Math.max(...values),
        unit: series[0]?.unit ?? "",
      };
    });
  }, [observations]);

  const domain = useMemo(() => {
    const times = observations.map((o) => +new Date(o.recorded_at));
    return { start: Math.min(...times), end: Math.max(...times) };
  }, [observations]);

  if (lanes.length === 0 || !Number.isFinite(domain.start)) {
    return (
      <div className="hatch-band border border-rule p-10 text-center text-[13px] text-ink-mid">
        No observations plotted yet.
      </div>
    );
  }

  // Narrow screens give the labels less room and the trace more.
  const narrow = width < 560;
  const GUTTER = narrow ? GUTTER_NARROW : GUTTER_WIDE;
  const RIGHT = narrow ? RIGHT_NARROW : RIGHT_WIDE;
  const plotW = Math.max(90, width - GUTTER - RIGHT);
  const height = RIBBON + lanes.length * LANE + AXIS;
  const span = Math.max(1, domain.end - domain.start);
  const scaleX = (iso: string | number) =>
    GUTTER + ((+new Date(iso) - domain.start) / span) * plotW;

  /** Events that get a rule drawn through every lane. */
  const marks = [
    ...doses.map((dose) => ({
      at: dose.administered_at,
      kind: "dose" as const,
      label: `D${dose.dose_number}`,
      title: `Dose ${dose.dose_number} · ${dose.amount} ${dose.unit}`,
    })),
    ...interventions.map((intervention) => ({
      at: intervention.raised_at,
      kind: "intervention" as const,
      label: "!",
      title: intervention.action.replace(/_/g, " ").toLowerCase(),
    })),
  ].filter((mark) => {
    const x = +new Date(mark.at);
    return x >= domain.start && x <= domain.end;
  });

  // A dose given before this window is why the window looks like it does, so
  // it is flagged at the edge rather than silently dropped.
  const earlierDoses = doses.filter(
    (dose) => +new Date(dose.administered_at) < domain.start,
  );

  const transitionX =
    transition && +new Date(transition.occurred_at) >= domain.start
      ? Math.min(scaleX(transition.occurred_at), GUTTER + plotW)
      : null;

  // The risk band across the window: one level before the transition, another
  // after it. With no transition the whole window carries the current level.
  const bands = transitionX
    ? [
        {
          from: GUTTER,
          to: transitionX,
          level: transition?.from_level ?? ("UNKNOWN" as RiskLevel),
        },
        { from: transitionX, to: GUTTER + plotW, level: riskLevel },
      ]
    : [{ from: GUTTER, to: GUTTER + plotW, level: riskLevel }];

  const hoverTime =
    hoverX === null ? null : domain.start + ((hoverX - GUTTER) / plotW) * span;

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => ({
    x: GUTTER + fraction * plotW,
    label: new Date(domain.start + fraction * span).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
  }));

  return (
    <div ref={wrap} className="w-full overflow-x-auto">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Monitoring trajectory for ${lanes.length} vitals across ${observations.length} observations, risk ${riskLevel}`}
        onMouseMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          const x = event.clientX - box.left;
          setHoverX(x >= GUTTER && x <= GUTTER + plotW ? x : null);
        }}
        onMouseLeave={() => setHoverX(null)}
      >
        {/* Risk band: the clinical state of the window, above everything. */}
        {bands.map((band, index) => (
          <g key={index}>
            <rect
              x={band.from}
              y={0}
              width={Math.max(0, band.to - band.from)}
              height={RIBBON - 8}
              fill={RISK_FILL[band.level]}
              opacity={band.level === "UNKNOWN" ? 0.25 : 0.16}
            />
            <rect
              x={band.from}
              y={RIBBON - 11}
              width={Math.max(0, band.to - band.from)}
              height={3}
              fill={RISK_FILL[band.level]}
            />
            {band.to - band.from > 54 && (
              <text
                x={band.from + 6}
                y={RIBBON - 14}
                className="fill-ink-mid font-mono"
                fontSize="9"
                letterSpacing="0.1em"
              >
                {band.level}
              </text>
            )}
          </g>
        ))}
        <text
          x={GUTTER - 8}
          y={RIBBON - 12}
          textAnchor="end"
          className="fill-ink-faint font-mono"
          fontSize="9"
          letterSpacing="0.08em"
        >
          RISK
        </text>

        {/* The deteriorated stretch, behind everything: the reader should see
            where the window turned before reading any single lane. */}
        {transitionX !== null && riskLevel !== "GREEN" && (
          <rect
            x={transitionX}
            y={RIBBON}
            width={Math.max(0, GUTTER + plotW - transitionX)}
            height={lanes.length * LANE}
            fill={RISK_FILL[riskLevel]}
            opacity="0.06"
          />
        )}

        {lanes.map((lane, index) => {
          const top = RIBBON + index * LANE;
          const inner = LANE - 22;
          const range = lane.max - lane.min || 1;
          const y = (value: number) =>
            top + 11 + inner - ((value - lane.min) / range) * inner;

          const points = lane.series
            .map((o) => `${scaleX(o.recorded_at).toFixed(1)},${y(o.value).toFixed(1)}`)
            .join(" ");
          const length = lane.series.reduce((total, o, i) => {
            if (i === 0) return 0;
            const previous = lane.series[i - 1];
            return (
              total +
              Math.hypot(
                scaleX(o.recorded_at) - scaleX(previous.recorded_at),
                y(o.value) - y(previous.value),
              )
            );
          }, 0);

          const latest = lane.series[lane.series.length - 1];
          const hovered =
            hoverTime === null
              ? null
              : lane.series.reduce((best, o) =>
                  Math.abs(+new Date(o.recorded_at) - hoverTime) <
                  Math.abs(+new Date(best.recorded_at) - hoverTime)
                    ? o
                    : best,
                );

          return (
            <g key={lane.type}>
              {index > 0 && (
                <line
                  x1={GUTTER}
                  y1={top}
                  x2={GUTTER + plotW}
                  y2={top}
                  stroke="var(--color-rule)"
                  strokeWidth="1"
                />
              )}

              <text
                x={GUTTER - 8}
                y={top + LANE / 2 - 3}
                textAnchor="end"
                className="fill-ink font-mono"
                fontSize="11"
              >
                {SHORT[lane.type]}
              </text>
              <text
                x={GUTTER - 8}
                y={top + LANE / 2 + 10}
                textAnchor="end"
                className="fill-ink-faint font-mono"
                fontSize="9"
              >
                {lane.unit}
              </text>

              {/* The patient's own first reading, for the trace to move against. */}
              <line
                x1={GUTTER}
                y1={y(lane.series[0].value)}
                x2={GUTTER + plotW}
                y2={y(lane.series[0].value)}
                stroke="var(--color-rule)"
                strokeWidth="1"
                strokeDasharray="2 4"
              />

              {/* A little body under the trace so the lane reads as a signal
                  rather than as a hairline. */}
              <polygon
                points={`${GUTTER},${top + LANE - 6} ${points} ${GUTTER + plotW},${top + LANE - 6}`}
                fill="var(--color-ink)"
                opacity="0.04"
              />
              <polyline
                points={points}
                fill="none"
                stroke="var(--color-ink)"
                strokeWidth="1.6"
                strokeLinejoin="round"
                strokeLinecap="round"
                className="animate-draw"
                style={
                  {
                    "--draw-length": length.toFixed(0),
                    animationDelay: `${index * 70}ms`,
                  } as React.CSSProperties
                }
              />

              {latest && (
                <>
                  <circle
                    cx={scaleX(latest.recorded_at)}
                    cy={y(latest.value)}
                    r="3"
                    fill="var(--color-panel)"
                    stroke="var(--color-ink)"
                    strokeWidth="1.6"
                  />
                  {!narrow && (
                  <text
                    x={Math.min(scaleX(latest.recorded_at) + 8, width - 4)}
                    y={Math.min(
                      Math.max(y(latest.value) + 4, top + 12),
                      top + LANE - 6,
                    )}
                    className="fill-ink font-mono"
                    fontSize="10.5"
                    fontWeight="500"
                  >
                    {latest.value}
                  </text>
                  )}
                </>
              )}

              {hovered && hoverX !== null && (
                <circle
                  cx={scaleX(hovered.recorded_at)}
                  cy={y(hovered.value)}
                  r="3.5"
                  fill="var(--color-signal)"
                />
              )}
            </g>
          );
        })}

        {/* Clinical events, drawn through every lane so cause sits above effect. */}
        {marks.map((mark, index) => {
          const x = scaleX(mark.at);
          const dose = mark.kind === "dose";
          return (
            <g key={`${mark.kind}-${index}`}>
              <title>{mark.title}</title>
              <line
                x1={x}
                y1={RIBBON}
                x2={x}
                y2={RIBBON + lanes.length * LANE}
                stroke={dose ? "var(--color-ink)" : "var(--color-alert)"}
                strokeWidth="1"
                strokeDasharray={dose ? undefined : "3 3"}
                opacity={dose ? 0.55 : 0.75}
              />
              <rect
                x={x - 9}
                y={RIBBON + 1}
                width="18"
                height="12"
                fill={dose ? "var(--color-ink)" : "var(--color-alert)"}
              />
              <text
                x={x}
                y={RIBBON + 10}
                textAnchor="middle"
                className="fill-paper font-mono"
                fontSize="8.5"
                fontWeight="600"
              >
                {mark.label}
              </text>
            </g>
          );
        })}

        {earlierDoses.length > 0 && (
          <g>
            <title>
              {earlierDoses
                .map((dose) => `Dose ${dose.dose_number} given before this window`)
                .join(", ")}
            </title>
            <rect x={GUTTER - 3} y={RIBBON} width="3" height={lanes.length * LANE} fill="var(--color-ink)" />
            <text
              x={GUTTER + 4}
              y={RIBBON + lanes.length * LANE - 5}
              className="fill-ink-faint font-mono"
              fontSize="8.5"
            >
              {`D${earlierDoses[earlierDoses.length - 1].dose_number} before window`}
            </text>
          </g>
        )}

        {transitionX !== null && (
          <g>
            <line
              x1={transitionX}
              y1={0}
              x2={transitionX}
              y2={RIBBON + lanes.length * LANE}
              stroke="var(--color-signal-deep)"
              strokeWidth="1.5"
            />
            <circle cx={transitionX} cy={RIBBON - 9.5} r="3.5" fill="var(--color-signal-deep)" />
          </g>
        )}

        {hoverX !== null && (
          <line
            x1={hoverX}
            y1={RIBBON}
            x2={hoverX}
            y2={RIBBON + lanes.length * LANE}
            stroke="var(--color-signal)"
            strokeWidth="1"
          />
        )}

        {/* Time axis */}
        <line
          x1={GUTTER}
          y1={RIBBON + lanes.length * LANE}
          x2={GUTTER + plotW}
          y2={RIBBON + lanes.length * LANE}
          stroke="var(--color-rule-strong)"
          strokeWidth="1"
        />
        {ticks.map((tick, index) => (
          <text
            key={index}
            x={tick.x}
            y={height - 8}
            textAnchor={index === 0 ? "start" : index === ticks.length - 1 ? "end" : "middle"}
            className="fill-ink-faint font-mono"
            fontSize="9.5"
          >
            {tick.label}
          </text>
        ))}
      </svg>

      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-rule pt-2 text-[10px] text-ink-faint">
        <Key mark={<span className="inline-block h-2.5 w-2.5 bg-ink" />} label="dose given" />
        <Key
          mark={<span className="inline-block h-2.5 w-2.5 bg-alert" />}
          label="protocol intervention"
        />
        <Key
          mark={<span className="inline-block h-2.5 w-2.5 rounded-full bg-signal-deep" />}
          label="risk transition"
        />
        <Key
          mark={<span className="inline-block h-0 w-4 border-t border-dashed border-rule-strong" />}
          label="patient's own baseline"
        />
        <span className="ml-auto">
          {observations.length} readings · hover to inspect
        </span>
      </div>
    </div>
  );
}

function Key({ mark, label }: { mark: React.ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {mark}
      {label}
    </span>
  );
}
