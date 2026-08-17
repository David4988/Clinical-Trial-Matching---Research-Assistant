import { useState } from "react";
import type { ApiError, ReviewDecision, ScreeningResult } from "../types/canonical";

/**
 * The human review step: where a screening stops being a report and becomes a
 * decision someone signed.
 *
 * Two deliberate constraints, both mirroring the backend:
 *
 *  * Nothing here can edit a verdict. The panel writes a review beside the
 *    result and the deterministic fields are re-rendered from the response
 *    unchanged. There is no control that alters a criterion.
 *  * Neither action is the default. Approve and request-further-review are
 *    presented with equal weight, because a reviewer skimming to the primary
 *    button is exactly the failure this step exists to prevent.
 *
 * A reviewer name and a reason are both required — an unsigned or unexplained
 * decision is refused by the service, so the form refuses it too rather than
 * bouncing the reviewer off a server error.
 */

const REASONS: Partial<Record<string, string>> = {
  REVIEW_REQUIRED: "The deterministic engine could not settle this screening alone.",
  ELIGIBLE: "The rules cleared every criterion. A reviewer still signs enrolment.",
};

export function ReviewPanel({
  result,
  busy,
  error,
  onSubmit,
}: {
  result: ScreeningResult;
  busy: boolean;
  error: ApiError | null;
  onSubmit: (decision: ReviewDecision, reviewer: string, note: string) => void;
}) {
  const [decision, setDecision] = useState<ReviewDecision | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");

  const ready = decision !== null && reviewer.trim() !== "" && note.trim() !== "";
  const conflicts = result.disagreements.length;

  return (
    <section aria-labelledby="review-heading">
      <div className="border border-rule-strong bg-panel">
        <div className="hatch h-1.5" />

        <div className="p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="review-heading" className="text-[13px] font-semibold tracking-[0.08em]">
              REVIEWER DECISION
            </h2>
            <span className="text-[11px] text-ink-faint">
              result {result.result_id}
            </span>
          </div>

          <p className="mt-1.5 max-w-2xl font-sans text-[13px] leading-relaxed text-ink-mid">
            {REASONS[result.overall_status] ??
              "This screening is recorded and awaiting a human decision."}
          </p>

          <WhyList result={result} conflicts={conflicts} />

          <fieldset className="mt-4 border-t border-rule pt-4">
            <legend className="sr-only">Decision</legend>
            <div className="eyebrow mb-2">Decision</div>
            <div className="grid gap-px bg-rule sm:grid-cols-2">
              <DecisionOption
                label="Approve for Phase 2"
                detail="Enrols this participant and carries your name and reason onto the treatment record."
                selected={decision === "APPROVED_FOR_PHASE_2"}
                onSelect={() => setDecision("APPROVED_FOR_PHASE_2")}
              />
              <DecisionOption
                label="Request further review"
                detail="Records that this screening is not ready. Enrolment stays blocked until an approval is recorded."
                selected={decision === "FURTHER_REVIEW_REQUESTED"}
                onSelect={() => setDecision("FURTHER_REVIEW_REQUESTED")}
              />
            </div>
          </fieldset>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field
              id="reviewer"
              label="Reviewer"
              placeholder="Name and role"
              value={reviewer}
              onChange={setReviewer}
            />
            <Field
              id="review-note"
              label="Reason"
              placeholder="What did you conclude, and why?"
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
              onClick={() => decision && onSubmit(decision, reviewer.trim(), note.trim())}
              className="border border-ink bg-ink px-4 py-2 text-[12px] font-medium text-paper transition-opacity hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-30"
            >
              {busy ? "Recording…" : "Confirm decision"}
            </button>
            <span className="font-sans text-[11px] leading-relaxed text-ink-faint">
              {ready
                ? "This decision is recorded against your name and appears on the timeline."
                : "Choose a decision, then record who you are and why."}
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

function WhyList({ result, conflicts }: { result: ScreeningResult; conflicts: number }) {
  const items = [
    conflicts > 0
      ? `${conflicts} rule/AI interpretation conflict${conflicts === 1 ? "" : "s"} — the advisory layer read at least one criterion differently from the engine.`
      : null,
    result.unknown_count > 0
      ? `${result.unknown_count} criterion could not be evaluated from the record and was left UNKNOWN rather than guessed.`
      : null,
    result.rule_coverage < 1
      ? `${Math.round(result.rule_coverage * 100)}% rule coverage — the rest of the protocol was not machine-verifiable.`
      : null,
  ].filter(Boolean) as string[];

  if (items.length === 0) return null;

  return (
    <ul className="mt-3 space-y-1.5 border-l-2 border-rule-strong pl-3">
      {items.map((item, index) => (
        <li key={index} className="font-sans text-[12px] leading-relaxed text-ink-mid">
          {item}
        </li>
      ))}
    </ul>
  );
}

function DecisionOption({
  label,
  detail,
  selected,
  onSelect,
}: {
  label: string;
  detail: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`p-3 text-left transition-colors ${
        selected ? "bg-ink text-paper" : "bg-panel hover:bg-band"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className={`inline-block h-2.5 w-2.5 shrink-0 border ${
            selected ? "border-paper bg-paper" : "border-rule-strong"
          }`}
        />
        <span className="text-[13px] font-medium">{label}</span>
      </div>
      <p
        className={`mt-1 font-sans text-[11px] leading-relaxed ${
          selected ? "text-paper/75" : "text-ink-faint"
        }`}
      >
        {detail}
      </p>
    </button>
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

/** The recorded decision, once one exists. Read-only and permanent. */
export function ReviewRecord({ review }: { review: NonNullable<ScreeningResult["review"]> }) {
  const approved = review.decision === "APPROVED_FOR_PHASE_2";

  return (
    <section className="border border-rule bg-panel">
      <div className={approved ? "h-1.5 bg-ink" : "hatch h-1.5"} />
      <div className="p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-[13px] font-semibold tracking-[0.08em]">
            {approved ? "APPROVED FOR PHASE 2" : "FURTHER REVIEW REQUESTED"}
          </span>
          <span className="text-[11px] text-ink-faint">
            {new Date(review.decided_at).toLocaleString()}
          </span>
        </div>
        <p className="mt-1.5 font-sans text-[13px] leading-relaxed text-ink">
          {review.note}
        </p>
        <p className="mt-2 text-[11px] text-ink-mid">
          {review.reviewer} · reviewed a {review.reviewed_status.replace(/_/g, " ")}{" "}
          screening
        </p>
      </div>
    </section>
  );
}
