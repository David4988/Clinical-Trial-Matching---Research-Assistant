import { useState } from "react";
import type { ApiError } from "../../types/canonical";
import type {
  InvestigatorAction,
  InvestigatorReview,
  MonitoringCycleResult,
} from "../../types/monitoring";

/**
 * The investigator's turn.
 *
 * Placed after the protocol response on purpose: by the time a reader reaches
 * this panel they have already seen what the model said, what the trust gate
 * did with it, and which actions the protocol requires. This is where a person
 * responds to all of that.
 *
 * The actions here are NOT the protocol's actions. `InterventionAction` is what
 * the deterministic layer mandates; `InvestigatorAction` is what a human
 * decided. Keeping them visually and structurally distinct is what stops the
 * screen from implying the model ordered anything.
 */

const ACTIONS: {
  action: InvestigatorAction;
  label: string;
  detail: string;
}[] = [
  {
    action: "ACKNOWLEDGE",
    label: "Acknowledge",
    detail: "Records that a named person has seen this signal. Changes nothing else.",
  },
  {
    action: "CONTINUE_MONITORING",
    label: "Continue monitoring",
    detail: "Reviewed, and the course proceeds under the current protocol cadence.",
  },
  {
    action: "HOLD_TREATMENT",
    label: "Hold treatment",
    detail: "Places the treatment ON HOLD. No further doses can be recorded.",
  },
];

export function InvestigatorPanel({
  cycle,
  reviews,
  busy,
  error,
  onSubmit,
}: {
  cycle: MonitoringCycleResult;
  reviews: InvestigatorReview[];
  busy: boolean;
  error: ApiError | null;
  onSubmit: (action: InvestigatorAction, reviewer: string, note: string) => void;
}) {
  const [action, setAction] = useState<InvestigatorAction | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");

  const ready = action !== null && reviewer.trim() !== "" && note.trim() !== "";
  const level = cycle.effective_risk.level;
  const urgent = level === "RED";
  // What the deterministic layer required, named beside what the human chose,
  // so the two are never read as the same act.
  const required = cycle.interventions.length
    ? cycle.interventions
        .map((i) => i.action.replace(/_/g, " ").toLowerCase())
        .join(", ")
    : null;

  return (
    <section aria-labelledby="investigator-heading" className="space-y-3">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-rule pb-2">
        <div className="flex items-baseline gap-3">
          <span className="readout text-[11px] text-ink-faint">05</span>
          <h2 id="investigator-heading" className="title text-[17px]">
            What the investigator decides
          </h2>
          <span className="text-[10px] font-semibold tracking-[0.12em] text-ink">
            HUMAN
          </span>
        </div>
        <span className="readout text-[11px] text-ink-faint">
          cycle {cycle.cycle_id}
        </span>
      </div>

      <div className="border border-rule bg-panel">
        <div className={urgent ? "h-1.5 bg-alert" : "h-1.5 bg-band"} />
        <div className="p-4">
          <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-rule pb-3">
            <span className="eyebrow">Protocol asked for</span>
            <span className="font-sans text-[13px] font-medium">
              {required ?? "no action"}
            </span>
            <span aria-hidden className="text-ink-faint">→</span>
            <span className="eyebrow">a named person answers</span>
          </div>

          <p className="font-sans text-[13px] leading-relaxed text-ink">
            {urgent
              ? "The protocol has escalated this participant. A named investigator must record a decision."
              : `Effective risk is ${level}. Recording a decision is how this cycle is signed off.`}
          </p>

          <fieldset className="mt-4">
            <legend className="sr-only">Investigator action</legend>
            <div className="grid gap-px bg-rule sm:grid-cols-3">
              {ACTIONS.map((option) => (
                <button
                  key={option.action}
                  type="button"
                  aria-pressed={action === option.action}
                  onClick={() => setAction(option.action)}
                  className={`p-3 text-left transition-colors ${
                    action === option.action
                      ? "bg-ink text-paper"
                      : "bg-panel hover:bg-band"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className={`inline-block h-2.5 w-2.5 shrink-0 border ${
                        action === option.action
                          ? "border-paper bg-paper"
                          : "border-rule-strong"
                      }`}
                    />
                    <span className="text-[13px] font-medium">{option.label}</span>
                  </div>
                  <p
                    className={`mt-1 font-sans text-[11px] leading-relaxed ${
                      action === option.action ? "text-paper/75" : "text-ink-faint"
                    }`}
                  >
                    {option.detail}
                  </p>
                </button>
              ))}
            </div>
          </fieldset>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field
              id="investigator-name"
              label="Investigator"
              placeholder="Name and role"
              value={reviewer}
              onChange={setReviewer}
            />
            <Field
              id="investigator-note"
              label="Reason"
              placeholder="What did you decide, and why?"
              value={note}
              onChange={setNote}
            />
          </div>

          {error && (
            <div className="mt-3 border border-alert/35 bg-alert-wash p-3">
              <div className="text-[10px] font-semibold tracking-[0.12em] text-alert">
                {error.code}
              </div>
              <p className="mt-0.5 font-sans text-[13px] text-ink">{error.message}</p>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-rule pt-4">
            <button
              type="button"
              disabled={!ready || busy}
              onClick={() => action && onSubmit(action, reviewer.trim(), note.trim())}
              className="border border-ink bg-ink px-4 py-2 text-[12px] font-medium text-paper hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-30"
            >
              {busy ? "Recording…" : "Record decision"}
            </button>
            <span className="font-sans text-[11px] leading-relaxed text-ink-faint">
              The risk assessment is not altered by this decision.
            </span>
          </div>
        </div>
      </div>

      {reviews.length > 0 && <ReviewLog reviews={reviews} />}
    </section>
  );
}

function ReviewLog({ reviews }: { reviews: InvestigatorReview[] }) {
  return (
    <div className="border border-rule bg-panel">
      <div className="eyebrow border-b border-rule p-3">
        Recorded decisions ({reviews.length})
      </div>
      <ul>
        {[...reviews].reverse().map((review, index) => (
          <li
            key={review.review_id}
            className={`p-3 ${index > 0 ? "border-t border-rule" : ""}`}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-[13px] font-medium">
                {review.action.replace(/_/g, " ").toLowerCase()}
              </span>
              <span className="text-[11px] text-ink-faint">
                {new Date(review.reviewed_at).toLocaleString()}
              </span>
            </div>
            <p className="mt-1 font-sans text-[12px] leading-relaxed text-ink-mid">
              {review.note}
            </p>
            <div className="mt-1 flex flex-wrap gap-x-3 text-[10px] tracking-[0.08em] text-ink-faint">
              <span>{review.reviewer}</span>
              <span>ON {review.risk_level}</span>
              {review.treatment_status_after && (
                <span>TREATMENT {review.treatment_status_after}</span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Field({
  id,
  label,
  placeholder,
  value,
  onChange,
}: {
  id: string;
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="eyebrow mb-1 block">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full border border-rule-strong bg-paper px-3 py-2 font-sans text-[13px] text-ink placeholder:text-ink-faint focus:border-ink focus:outline-none"
      />
    </div>
  );
}
