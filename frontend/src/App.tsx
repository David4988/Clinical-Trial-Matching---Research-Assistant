import { useState } from "react";
import {
  ScreeningApiError,
  recordReview,
  screenCanonical,
  screenPdf,
} from "./api/client";
import { recordDose, registerTreatment } from "./api/monitoring";
import { SAMPLE_PATIENT, SAMPLE_TRIAL } from "./api/sample";
import { AIPanel } from "./components/AIPanel";
import { AdministrationPanel } from "./components/AdministrationPanel";
import { CriterionLedger } from "./components/CriterionLedger";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ReviewPanel, ReviewRecord } from "./components/ReviewPanel";
import { ScreeningHeader } from "./components/ScreeningHeader";
import { UploadPanel } from "./components/UploadPanel";
import { MonitoringApp } from "./components/monitoring/MonitoringApp";
import type { MonitoringFocus } from "./components/monitoring/MonitoringApp";
import type {
  ApiError,
  ReviewDecision,
  ScreeningResult,
} from "./types/canonical";
import type { TreatmentAssignment } from "./types/monitoring";

/**
 * Two phases, one shell — and one participant carried between them.
 *
 * Phase 1 (screening) keeps its original flow. What is new is the continuation:
 * a screened participant is reviewed, enrolled and dosed in place, and then
 * handed to Phase 2 monitoring by identity. `focus` is that handoff, and it is
 * the reason the judge never has to go and find the patient again in an
 * unrelated cohort.
 *
 * The step order here is the product story, and it is enforced by the backend
 * rather than by this component: a screening cannot be enrolled without a
 * recorded review, and a review that asked for more review blocks enrolment.
 */

type Mode = "screening" | "monitoring";

type View =
  | { kind: "upload" }
  | { kind: "processing" }
  | { kind: "report"; result: ScreeningResult };

export default function App() {
  const [mode, setMode] = useState<Mode>("screening");
  const [view, setView] = useState<View>({ kind: "upload" });
  const [error, setError] = useState<ApiError | null>(null);
  const [stepError, setStepError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [treatment, setTreatment] = useState<TreatmentAssignment | null>(null);
  const [focus, setFocus] = useState<MonitoringFocus | null>(null);

  const asApiError = (err: unknown, fallback: string): ApiError =>
    err instanceof ScreeningApiError
      ? err.error
      : {
          code: "NETWORK_ERROR",
          message: fallback,
          details: ["Confirm the backend is running on port 8000."],
        };

  async function run(work: () => Promise<ScreeningResult>) {
    setError(null);
    setStepError(null);
    setTreatment(null);
    setView({ kind: "processing" });
    try {
      setView({ kind: "report", result: await work() });
    } catch (err) {
      setError(asApiError(err, "Could not reach the screening service."));
      setView({ kind: "upload" });
    }
  }

  /**
   * Record the decision, and — when it is an approval — carry the participant
   * straight into Phase 2. Enrolment sends no override: the review that was
   * just recorded is what authorises it, and the backend reads it from the
   * screening itself.
   */
  async function onReview(
    decision: ReviewDecision,
    reviewer: string,
    note: string,
  ) {
    if (view.kind !== "report") return;

    setBusy(true);
    setStepError(null);
    try {
      const reviewed = await recordReview(
        view.result.result_id,
        decision,
        reviewer,
        note,
      );
      setView({ kind: "report", result: reviewed });

      if (decision === "APPROVED_FOR_PHASE_2") {
        setTreatment(
          await registerTreatment(reviewed.result_id, "Compound X"),
        );
      }
    } catch (err) {
      setStepError(asApiError(err, "Could not record the review."));
    } finally {
      setBusy(false);
    }
  }

  async function onAdminister(dose: {
    amount: number;
    unit: string;
    route: string;
    administered_by: string;
  }) {
    if (!treatment) return;

    setBusy(true);
    setStepError(null);
    try {
      setTreatment(await recordDose(treatment.treatment_id, dose));
    } catch (err) {
      setStepError(asApiError(err, "Could not record the administration."));
    } finally {
      setBusy(false);
    }
  }

  function onOpenMonitoring() {
    if (!treatment) return;
    setFocus({ patientId: treatment.patient_id, trialId: treatment.trial_id });
    setMode("monitoring");
  }

  function onReset() {
    setView({ kind: "upload" });
    setTreatment(null);
    setFocus(null);
    setStepError(null);
    setError(null);
  }

  return (
    <div className="min-h-screen">
      <Header
        mode={mode}
        onMode={(next) => {
          // Leaving the handoff behind returns monitoring to the cohort board.
          if (next === "monitoring" && !treatment) setFocus(null);
          setMode(next);
        }}
        onReset={mode === "screening" && view.kind === "report" ? onReset : undefined}
      />

      <main className="mx-auto max-w-5xl px-5 py-8">
        <ErrorBoundary key={mode}>
          {mode === "monitoring" ? (
            <MonitoringApp focus={focus} />
          ) : view.kind === "report" ? (
            <div className="space-y-8">
              <ScreeningHeader result={view.result} />
              <CriterionLedger result={view.result} />
              <AIPanel
                analysis={view.result.ai_analysis}
                disagreements={view.result.disagreements}
              />

              {view.result.review ? (
                <ReviewRecord review={view.result.review} />
              ) : (
                <ReviewPanel
                  result={view.result}
                  busy={busy}
                  error={stepError}
                  onSubmit={onReview}
                />
              )}

              {treatment && (
                <AdministrationPanel
                  treatment={treatment}
                  busy={busy}
                  error={stepError}
                  onAdminister={onAdminister}
                  onOpenMonitoring={onOpenMonitoring}
                />
              )}

              {view.result.review && !treatment && stepError && (
                <EnrolmentBlocked error={stepError} />
              )}

              <Footer result={view.result} />
            </div>
          ) : (
            <UploadPanel
              busy={view.kind === "processing"}
              error={error}
              onFile={(file) => run(() => screenPdf(file))}
              onUseSample={() => run(() => screenCanonical(SAMPLE_PATIENT, SAMPLE_TRIAL))}
            />
          )}
        </ErrorBoundary>
      </main>
    </div>
  );
}

/** The product mark: one observation window, read left to right. */
function Mark() {
  return (
    <span
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center border border-rule bg-paper"
    >
      <svg width="20" height="14" viewBox="0 0 20 14" fill="none">
        <path
          d="M1 9.5h3.2l1.6-6 2.4 9 2-4.5h2.2"
          stroke="var(--color-ink)"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="16.5" cy="8" r="2.5" fill="var(--color-signal)" />
      </svg>
    </span>
  );
}

/** Shown when a recorded review did not result in enrolment. */
function EnrolmentBlocked({ error }: { error: ApiError }) {
  return (
    <section className="border border-rule-strong bg-panel">
      <div className="hatch h-1.5" />
      <div className="p-4">
        <div className="text-[10px] font-semibold tracking-[0.12em] text-ink">
          {error.code}
        </div>
        <p className="mt-1 font-sans text-[13px] leading-relaxed text-ink">
          {error.message}
        </p>
        {error.details.length > 0 && (
          <ul className="mt-2 space-y-1 font-sans text-[12px] text-ink-mid">
            {error.details.map((detail, index) => (
              <li key={index}>{detail}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function Header({
  mode,
  onMode,
  onReset,
}: {
  mode: Mode;
  onMode: (mode: Mode) => void;
  onReset?: () => void;
}) {
  return (
    <header className="border-b border-rule bg-panel">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-5 py-3">
        <div className="flex items-center gap-3">
          <Mark />
          <div>
            <div className="font-sans text-[15px] font-semibold tracking-[-0.02em] leading-none">
              TrialGuard<span className="text-signal-deep"> AI</span>
            </div>
            <div className="mt-1 text-[10px] tracking-[0.12em] text-ink-faint">
              {mode === "screening"
                ? "PHASE 1 · RULES AUTHORITATIVE"
                : "PHASE 2 · PROTOCOL AUTHORITATIVE"}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <nav className="flex border border-rule-strong" aria-label="Phase">
            <ModeButton
              label="Screening"
              active={mode === "screening"}
              onClick={() => onMode("screening")}
            />
            <ModeButton
              label="Monitoring"
              active={mode === "monitoring"}
              onClick={() => onMode("monitoring")}
            />
          </nav>

          {onReset && (
            <button
              type="button"
              onClick={onReset}
              className="border border-rule-strong px-3 py-1.5 text-[12px] hover:border-ink"
            >
              New screening
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

function ModeButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={`px-3 py-1.5 text-[12px] ${
        active ? "bg-ink text-paper" : "text-ink-mid hover:text-ink"
      }`}
    >
      {label}
    </button>
  );
}

function Footer({ result }: { result: ScreeningResult }) {
  return (
    <footer className="border-t border-rule pt-4 text-[11px] text-ink-faint">
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>Result {result.result_id}</span>
        <span>Generated {new Date(result.generated_at).toLocaleString()}</span>
        <span>Saved to the local repository</span>
      </div>
      <p className="mt-2 max-w-2xl font-sans leading-relaxed">
        Screening decisions come from deterministic rules. Heuristics and the
        mock AI layer are advisory and cannot change a verdict. Review and
        enrolment decisions are recorded against a named person.
      </p>
    </footer>
  );
}
