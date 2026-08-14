import type { CriterionStatus, OverallStatus } from "../types/canonical";

/**
 * Verdict is carried by shape and position before colour.
 *
 * The rail is solid for PASS, crimson for FAIL, and hatched for UNKNOWN, so
 * the three states remain distinguishable in greyscale and to a colour-blind
 * reader. The token repeats the verdict in words for screen readers.
 */

export function VerdictRail({ status }: { status: CriterionStatus }) {
  const className =
    status === "FAIL"
      ? "bg-alert"
      : status === "UNKNOWN"
        ? "hatch"
        : "bg-ink";
  return <div className={`w-[3px] shrink-0 self-stretch ${className}`} />;
}

export function VerdictToken({ status }: { status: CriterionStatus }) {
  const styles: Record<CriterionStatus, string> = {
    PASS: "text-ink border-ink/30",
    FAIL: "text-alert border-alert/40 bg-alert-wash",
    UNKNOWN: "text-ink-mid border-rule-strong border-dashed",
  };
  return (
    <span
      className={`inline-block border px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.12em] ${styles[status]}`}
    >
      {status}
    </span>
  );
}

const OVERALL_COPY: Record<OverallStatus, { label: string; note: string }> = {
  ELIGIBLE: {
    label: "ELIGIBLE",
    note: "Every criterion was verified deterministically and passed.",
  },
  INELIGIBLE: {
    label: "INELIGIBLE",
    note: "At least one criterion failed a deterministic rule.",
  },
  REVIEW_REQUIRED: {
    label: "REVIEW REQUIRED",
    note: "This screening cannot be decided automatically.",
  },
};

export function OverallBanner({
  status,
  reason,
}: {
  status: OverallStatus;
  reason: string;
}) {
  const copy = OVERALL_COPY[status];
  const isAlert = status === "INELIGIBLE";
  const isReview = status === "REVIEW_REQUIRED";

  return (
    <div
      className={`flex gap-4 border p-4 ${
        isAlert ? "border-alert/35 bg-alert-wash" : "border-rule bg-panel"
      }`}
    >
      <div
        className={`w-1 shrink-0 ${
          isAlert ? "bg-alert" : isReview ? "hatch" : "bg-ink"
        }`}
      />
      <div className="min-w-0">
        <div
          className={`text-xl font-semibold tracking-[0.06em] ${
            isAlert ? "text-alert" : "text-ink"
          }`}
        >
          {copy.label}
        </div>
        <p className="mt-1 max-w-2xl font-sans text-sm text-ink-mid">
          {reason || copy.note}
        </p>
      </div>
    </div>
  );
}
