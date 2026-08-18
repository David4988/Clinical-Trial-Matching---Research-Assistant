import { useState } from "react";
import type { MonitoringEvent } from "../../types/monitoring";

/**
 * The append-only record, oldest first:
 * dose -> observations -> risk -> transitions -> alerts -> intervention -> next dose.
 *
 * Rendered from the event log rather than by joining six collections at display
 * time, which is why the ordering is trustworthy: it is the order things were
 * actually written.
 */

const GLYPH: Record<string, string> = {
  TREATMENT_REGISTERED: "◆",
  ELIGIBILITY_OVERRIDE_RECORDED: "!",
  DOSE_ADMINISTERED: "●",
  OBSERVATIONS_INGESTED: "·",
  RISK_ASSESSED: "◇",
  RISK_TRANSITION: "→",
  DATA_QUALITY_GATE_APPLIED: "▨",
  INTERVENTION_RAISED: "▸",
  NOTIFICATION_CREATED: "✉",
  NEXT_DOSE_ASSESSED: "◼",
  ADVERSE_EVENT_RECORDED: "▲",
};

/** Events that mark a change of state rather than routine throughput. */
const EMPHASIS = new Set([
  "RISK_TRANSITION",
  "DATA_QUALITY_GATE_APPLIED",
  "ELIGIBILITY_OVERRIDE_RECORDED",
  "ADVERSE_EVENT_RECORDED",
]);

/** What a reader retelling this case would mention. */
const KEY_EVENTS = new Set([
  ...EMPHASIS,
  "TREATMENT_REGISTERED",
  "DOSE_ADMINISTERED",
  "INTERVENTION_RAISED",
  "NOTIFICATION_CREATED",
  "NEXT_DOSE_ASSESSED",
]);

/** Past this many rows the log stops being readable as a story. */
const FOLD_ABOVE = 14;

export function PatientTimeline({ events }: { events: MonitoringEvent[] }) {
  const foldable = events.length > FOLD_ABOVE;
  // Null means "follow the log": a short log shows in full, a long one folds to
  // its key events. An explicit click pins the choice from then on. Deriving it
  // per render matters because the log grows as cycles run.
  const [pinned, setPinned] = useState<boolean | null>(null);
  const showAll = pinned ?? !foldable;

  if (events.length === 0) {
    return (
      <section>
        <h2 className="eyebrow mb-2">Timeline</h2>
        <div className="border border-dashed border-rule-strong bg-panel p-6 text-center text-[13px] text-ink-mid">
          Nothing recorded yet.
        </div>
      </section>
    );
  }

  const shown = showAll ? events : events.filter((e) => KEY_EVENTS.has(e.event_type));

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="eyebrow">Timeline</h2>
        <div className="flex items-baseline gap-3">
          <span className="text-[11px] text-ink-faint">
            {showAll
              ? `${events.length} events · oldest first`
              : `${shown.length} of ${events.length} events · oldest first`}
          </span>
          {foldable && (
            <button
              type="button"
              onClick={() => setPinned(!showAll)}
              className="border border-rule-strong px-2 py-1 text-[11px] hover:border-ink"
            >
              {showAll ? "Key events only" : `Show all ${events.length}`}
            </button>
          )}
        </div>
      </div>

      <ol className="border border-rule bg-panel">
        {shown.map((event, index) => {
          const marked = EMPHASIS.has(event.event_type);
          return (
            <li
              key={event.event_id}
              className={`relative flex gap-3 py-2.5 pl-4 pr-3 ${
                index === shown.length - 1 ? "" : "border-b border-rule"
              } ${marked ? "bg-band/50" : ""}`}
            >
              {/* The spine: one continuous thread the glyphs sit on. */}
              <span
                aria-hidden
                className="absolute bottom-0 left-[1.55rem] top-0 w-px bg-rule"
              />
              <span
                className={`relative z-10 mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center border text-[10px] ${
                  marked
                    ? "border-ink bg-ink text-paper"
                    : "border-rule bg-panel text-ink-mid"
                }`}
                aria-hidden
              >
                {GLYPH[event.event_type] ?? "·"}
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span
                    className={`text-[10px] tracking-[0.08em] ${
                      marked ? "font-semibold text-ink" : "text-ink-faint"
                    }`}
                  >
                    {event.event_type.replace(/_/g, " ")}
                  </span>
                  <time className="readout text-[10px] text-ink-faint">
                    {new Date(event.occurred_at).toLocaleTimeString()}
                  </time>
                </div>
                <p
                  className={`mt-0.5 font-sans leading-relaxed ${
                    marked ? "text-[13px] text-ink" : "text-[12px] text-ink-mid"
                  }`}
                >
                  {event.summary}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
