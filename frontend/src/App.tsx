import { useState } from "react";
import { ScreeningApiError, screenCanonical, screenPdf } from "./api/client";
import { SAMPLE_PATIENT, SAMPLE_TRIAL } from "./api/sample";
import { AIPanel } from "./components/AIPanel";
import { CriterionLedger } from "./components/CriterionLedger";
import { ScreeningHeader } from "./components/ScreeningHeader";
import { UploadPanel } from "./components/UploadPanel";
import type { ApiError, ScreeningResult } from "./types/canonical";

type View =
  | { kind: "upload" }
  | { kind: "processing" }
  | { kind: "report"; result: ScreeningResult };

export default function App() {
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
        onReset={view.kind === "report" ? () => setView({ kind: "upload" }) : undefined}
      />

      <main className="mx-auto max-w-4xl px-5 py-8">
        {view.kind === "report" ? (
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

function Header({ onReset }: { onReset?: () => void }) {
  return (
    <header className="border-b border-rule bg-panel">
      <div className="mx-auto flex max-w-4xl items-center justify-between px-5 py-3">
        <div className="flex items-baseline gap-3">
          <span className="text-[13px] font-semibold tracking-[0.08em]">
            CLINICAL TRIAL SCREENING
          </span>
          <span className="text-[10px] tracking-[0.12em] text-ink-faint">
            PHASE 1 · RULES AUTHORITATIVE
          </span>
        </div>
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
    </header>
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
