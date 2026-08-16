import { useState } from "react";
import { ScreeningApiError, screenCanonical, screenPdf } from "./api/client";
import { SAMPLE_PATIENT, SAMPLE_TRIAL } from "./api/sample";
import { AIPanel } from "./components/AIPanel";
import { CriterionLedger } from "./components/CriterionLedger";
import { ScreeningHeader } from "./components/ScreeningHeader";
import { UploadPanel } from "./components/UploadPanel";
import { MonitoringApp } from "./components/monitoring/MonitoringApp";
import type { ApiError, ScreeningResult } from "./types/canonical";

/**
 * Two phases, one shell.
 *
 * Phase 1 (screening) is untouched: the same View union, the same components,
 * the same flow. Phase 2 (monitoring) is a sibling mode alongside it, so
 * nothing that worked before moves or changes behaviour.
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

  async function run(work: () => Promise<ScreeningResult>) {
    setError(null);
    setView({ kind: "processing" });
    try {
      setView({ kind: "report", result: await work() });
    } catch (err) {
      setError(
        err instanceof ScreeningApiError
          ? err.error
          : {
              code: "NETWORK_ERROR",
              message: "Could not reach the screening service.",
              details: ["Confirm the backend is running on port 8000."],
            },
      );
      setView({ kind: "upload" });
    }
  }

  return (
    <div className="min-h-screen">
      <Header
        mode={mode}
        onMode={setMode}
        onReset={
          mode === "screening" && view.kind === "report"
            ? () => setView({ kind: "upload" })
            : undefined
        }
      />

      <main className="mx-auto max-w-4xl px-5 py-8">
        {mode === "monitoring" ? (
          <MonitoringApp />
        ) : view.kind === "report" ? (
          <div className="space-y-8">
            <ScreeningHeader result={view.result} />
            <CriterionLedger result={view.result} />
            <AIPanel
              analysis={view.result.ai_analysis}
              disagreements={view.result.disagreements}
            />
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
      </main>
    </div>
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
      <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-5 py-3">
        <div className="flex items-baseline gap-3">
          <span className="text-[13px] font-semibold tracking-[0.08em]">
            CLINICAL TRIAL SCREENING
          </span>
          <span className="text-[10px] tracking-[0.12em] text-ink-faint">
            {mode === "screening"
              ? "PHASE 1 · RULES AUTHORITATIVE"
              : "PHASE 2 · PROTOCOL AUTHORITATIVE"}
          </span>
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
        mock AI layer are advisory and cannot change a verdict.
      </p>
    </footer>
  );
}
