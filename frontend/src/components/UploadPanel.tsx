import { useRef, useState } from "react";
import type { ApiError } from "../types/canonical";

interface Props {
  onFile: (file: File) => void;
  onUseSample: () => void;
  busy: boolean;
  error: ApiError | null;
}

export function UploadPanel({ onFile, onUseSample, busy, error }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  function accept(file: File | undefined) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setLocalError("Select a PDF. Phase 1 reads text-based clinical PDFs.");
      return;
    }
    setLocalError(null);
    onFile(file);
  }

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6">
        <h1 className="text-2xl font-medium tracking-[0.02em]">
          Screen a patient against a trial protocol
        </h1>
        <p className="mt-2 max-w-xl font-sans text-[14px] leading-relaxed text-ink-mid">
          Upload a structured clinical record. The engine checks each criterion
          against the patient's data, shows the evidence behind every verdict,
          and holds anything it cannot verify for human review.
        </p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          accept(e.dataTransfer.files[0]);
        }}
        className={`border-2 border-dashed p-10 text-center transition-colors ${
          dragging ? "border-ink bg-band" : "border-rule-strong bg-panel"
        }`}
      >
        {busy ? (
          <Processing />
        ) : (
          <>
            <div className="eyebrow mb-3">Structured clinical PDF</div>
            <p className="font-sans text-[14px] text-ink-mid">
              Drop a file here, or
            </p>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="mt-3 border border-ink bg-ink px-4 py-2 text-[13px] font-medium tracking-[0.04em] text-paper hover:bg-ink/90"
            >
              Select PDF
            </button>
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="sr-only"
              onChange={(e) => accept(e.target.files?.[0] ?? undefined)}
            />
            <div className="mt-4">
              <button
                type="button"
                onClick={onUseSample}
                className="text-[12px] text-ink-mid underline underline-offset-4 hover:text-ink"
              >
                Screen the sample record instead
              </button>
            </div>
          </>
        )}
      </div>

      {(error || localError) && (
        <ErrorNotice error={error} localMessage={localError} />
      )}
    </div>
  );
}

function Processing() {
  const steps = [
    "Extracting text",
    "Building canonical schema",
    "Applying deterministic rules",
    "Collecting evidence",
  ];
  return (
    <div>
      <div className="relative mx-auto mb-5 h-0.5 w-48 overflow-hidden bg-band">
        <div className="animate-sweep absolute inset-y-0 w-1/4 bg-signal" />
      </div>
      <div className="eyebrow mb-3">Screening in progress</div>
      {/* The pipeline, arriving in the order it actually runs. */}
      <ol className="stagger mx-auto inline-flex flex-col gap-1.5 text-left">
        {steps.map((step) => (
          <li
            key={step}
            className="flex items-center gap-2.5 font-sans text-[13px] text-ink-mid"
          >
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-signal" aria-hidden />
            {step}
          </li>
        ))}
      </ol>
    </div>
  );
}
function ErrorNotice({
  error,
  localMessage,
}: {
  error: ApiError | null;
  localMessage: string | null;
}) {
  return (
    <div className="mt-4 border border-alert/35 bg-alert-wash p-4">
      <div className="text-[10px] font-semibold tracking-[0.12em] text-alert">
        {error?.code ?? "INVALID_FILE"}
      </div>
      <p className="mt-1 font-sans text-[14px] text-ink">
        {error?.message ?? localMessage}
      </p>
      {error?.details && error.details.length > 0 && (
        <ul className="mt-2 space-y-1 font-sans text-[12px] text-ink-mid">
          {error.details.map((detail, index) => (
            <li key={index}>{detail}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
