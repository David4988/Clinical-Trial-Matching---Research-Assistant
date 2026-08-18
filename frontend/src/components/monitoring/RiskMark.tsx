import type { NextDoseDecision, RiskLevel } from "../../types/monitoring";

/**
 * Risk level carried by PATTERN first, colour second, words always.
 *
 * Each level keeps a fill that survives greyscale, so the screen still reads
 * with the colour removed:
 *
 *   GREEN    solid            AMBER   dense stripes
 *   RED      solid            UNKNOWN sparse hatch
 *
 * The written level sits beside the mark in every case, so nothing depends on
 * telling two hues apart. Colour reinforces; it never carries the state alone.
 */

const RAIL: Record<RiskLevel, string> = {
  GREEN: "bg-safe",
  AMBER: "stripe-caution",
  RED: "bg-alert",
  UNKNOWN: "hatch",
};

const TOKEN: Record<RiskLevel, string> = {
  GREEN: "text-safe border-safe/40 bg-safe-wash",
  AMBER: "text-caution border-caution/40 bg-caution-wash",
  RED: "text-alert border-alert/40 bg-alert-wash",
  UNKNOWN: "text-ink-mid border-rule-strong border-dashed bg-panel",
};

export function RiskRail({ level }: { level: RiskLevel }) {
  return <div className={`w-[3px] shrink-0 self-stretch ${RAIL[level]}`} />;
}

export function RiskToken({ level }: { level: RiskLevel }) {
  return (
    <span
      className={`inline-block border px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.12em] ${TOKEN[level]}`}
    >
      {level}
    </span>
  );
}

/**
 * The level at headline size, for the one place on the screen that answers
 * "what state is this participant in right now".
 */
export function RiskDisplay({ level }: { level: RiskLevel }) {
  return (
    <span
      className={`inline-flex items-center gap-2.5 border px-3 py-1.5 ${TOKEN[level]}`}
    >
      <span className={`h-4 w-4 shrink-0 border border-black/10 ${RAIL[level]}`} aria-hidden />
      <span className="text-[22px] font-semibold leading-none tracking-[0.06em]">
        {level}
      </span>
    </span>
  );
}

/** The level as a filled swatch plus its name — used in counts and tables. */
export function RiskChip({ level, count }: { level: RiskLevel; count?: number }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-block h-3 w-3 border border-rule-strong ${RAIL[level]}`}
        aria-hidden
      />
      <span className="text-[11px] tracking-[0.08em]">{level}</span>
      {count !== undefined && (
        <span className="text-[13px] font-medium tabular-nums">{count}</span>
      )}
    </span>
  );
}

const DOSE: Record<NextDoseDecision, string> = {
  PROCEED: "text-safe border-safe/40 bg-safe-wash",
  REVIEW_REQUIRED: "text-caution border-caution/40 bg-caution-wash",
  HOLD: "text-alert border-alert/40 bg-alert-wash",
};

export function DoseToken({ decision }: { decision: NextDoseDecision }) {
  return (
    <span
      className={`inline-block border px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.1em] ${DOSE[decision]}`}
    >
      {decision.replace("_", " ")}
    </span>
  );
}

const TREND_GLYPH: Record<string, string> = {
  RISING: "▲",
  FALLING: "▼",
  STABLE: "—",
  INSUFFICIENT_DATA: "·",
};

export function TrendMark({ trend }: { trend: string }) {
  return (
    <span className="text-[11px] text-ink-mid" title={trend.replace("_", " ").toLowerCase()}>
      {TREND_GLYPH[trend] ?? "·"}
    </span>
  );
}
