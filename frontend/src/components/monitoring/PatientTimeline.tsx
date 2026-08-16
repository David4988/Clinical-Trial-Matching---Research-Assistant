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

export function PatientTimeline({ events }: { events: MonitoringEvent[] }) {
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

  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="eyebrow">Timeline</h2>
        <span className="text-[11px] text-ink-faint">
          {events.length} events · oldest first
        </span>
      </div>

      <ol className="border border-rule bg-panel">
        {events.map((event, index) => (
          <li
            key={event.event_id}
            className={`flex gap-3 p-3 ${
              index === events.length - 1 ? "" : "border-b border-rule"
            } ${EMPHASIS.has(event.event_type) ? "bg-band/50" : ""}`}
          >
            <span
              className="mt-0.5 w-4 shrink-0 text-center text-[12px] text-ink-mid"
              aria-hidden
            >
              {GLYPH[event.event_type] ?? "·"}
            </span>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="text-[10px] tracking-[0.08em] text-ink-faint">
                  {event.event_type.replace(/_/g, " ")}
                </span>
                <time className="text-[10px] tabular-nums text-ink-faint">
                  {new Date(event.occurred_at).toLocaleString()}
                </time>
              </div>
              <p className="mt-0.5 font-sans text-[13px] leading-relaxed text-ink">
                {event.summary}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
