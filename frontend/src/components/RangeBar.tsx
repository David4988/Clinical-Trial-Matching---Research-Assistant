import type { CriterionStatus, NumericRule } from "../types/canonical";

/**
 * The signature element.
 *
 * Clinical lab reports plot a value against its reference range, and every
 * numeric criterion in a trial protocol is exactly that shape. Rendering it
 * this way means a reader sees PASS/FAIL *and* how close the call was without
 * reading a number — a value at 47 against a floor of 45 visibly hugs the
 * edge, which is precisely what the borderline heuristic flags.
 *
 * UNKNOWN gets a hatched track and no marker: missing data is drawn as
 * missing, not as a neutral grey state that could be mistaken for a verdict.
 */

interface Props {
  rule: NumericRule;
  observedValue: number | null;
  status: CriterionStatus;
}

function parseObserved(observed: string | null): number | null {
  if (!observed) return null;
  const match = observed.match(/-?\d+(\.\d+)?/);
  return match ? Number(match[0]) : null;
}

export function observedNumber(observed: string | null): number | null {
  return parseObserved(observed);
}

export function RangeBar({ rule, observedValue, status }: Props) {
  const { op, low, high } = rule;
  if (low === null) return null;

  const anchors = [low, high, observedValue].filter(
    (n): n is number => n !== null && Number.isFinite(n),
  );
  const rawMin = Math.min(...anchors);
  const rawMax = Math.max(...anchors);
  const span = rawMax - rawMin || Math.max(Math.abs(rawMax), 1);
  const pad = span * 0.28;
  const domainMin = rawMin - pad;
  const domainMax = rawMax + pad;

  const pct = (n: number) =>
    ((n - domainMin) / (domainMax - domainMin)) * 100;

  // Where the acceptable window sits within the drawn domain.
  let windowStart: number;
  let windowEnd: number;
  if (op === "between") {
    windowStart = pct(low);
    windowEnd = pct(high ?? low);
  } else if (op === "gte" || op === "gt") {
    windowStart = pct(low);
    windowEnd = 100;
  } else if (op === "lte" || op === "lt") {
    windowStart = 0;
    windowEnd = pct(low);
  } else {
    windowStart = pct(low) - 0.8;
    windowEnd = pct(low) + 0.8;
  }

  const isUnknown = status === "UNKNOWN" || observedValue === null;
  const markerPct = observedValue === null ? null : pct(observedValue);
  const markerColor = status === "FAIL" ? "var(--color-alert)" : "var(--color-ink)";

  const boundaryLabels: Array<{ at: number; text: string }> = [];
  if (op === "between" && high !== null) {
    boundaryLabels.push({ at: pct(low), text: format(low) });
    boundaryLabels.push({ at: pct(high), text: format(high) });
  } else {
    boundaryLabels.push({ at: pct(low), text: format(low) });
  }

  return (
    <div className="w-full select-none pt-1" aria-hidden="true">
      <div className="relative h-2">
        {/* Track */}
        <div
          className={`absolute inset-0 ${isUnknown ? "hatch-band" : "bg-band"}`}
        />

        {/* Acceptable window — must read as clearly distinct from the track,
            since "is the value inside the band?" is the whole question. */}
        {!isUnknown && (
          <div
            className="absolute top-0 bottom-0 bg-ink/30"
            style={{
              left: `${clamp(windowStart)}%`,
              width: `${Math.max(clamp(windowEnd) - clamp(windowStart), 0.6)}%`,
            }}
          />
        )}

        {/* Boundary ticks, overhanging the track so the window edges are legible */}
        {!isUnknown &&
          boundaryLabels.map((b) => (
            <div
              key={`tick-${b.at}`}
              className="absolute -top-0.5 -bottom-0.5 w-px bg-ink/70"
              style={{ left: `${clamp(b.at)}%` }}
            />
          ))}

        {/* Patient value */}
        {markerPct !== null && (
          <div
            className="absolute -top-1 -bottom-1 w-0.5"
            style={{ left: `${clamp(markerPct)}%`, background: markerColor }}
          >
            <div
              className="absolute left-1/2 -translate-x-1/2 -top-1 h-2 w-2 rounded-full"
              style={{ background: markerColor }}
            />
          </div>
        )}
      </div>

      {/* Scale labels */}
      <div className="relative mt-1 h-4 text-[10px] text-ink-faint">
        {!isUnknown &&
          boundaryLabels.map((b) => (
            <span
              key={`label-${b.at}`}
              className="absolute -translate-x-1/2 whitespace-nowrap"
              style={{ left: `${clamp(b.at, 4, 96)}%` }}
            >
              {b.text}
            </span>
          ))}
        {markerPct !== null && (
          <span
            className="absolute -translate-x-1/2 whitespace-nowrap font-medium"
            style={{
              left: `${clamp(markerPct, 4, 96)}%`,
              top: "0.7rem",
              color: markerColor,
            }}
          >
            {format(observedValue!)}
          </span>
        )}
        {isUnknown && (
          <span className="absolute left-0 text-ink-faint">
            no value recorded
          </span>
        )}
      </div>
    </div>
  );
}

function clamp(n: number, min = 0, max = 100) {
  return Math.min(Math.max(n, min), max);
}

function format(n: number) {
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(2)));
}
