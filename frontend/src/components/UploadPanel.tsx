import { useRef, useState } from "react";
import { SAMPLE_PATIENT, SAMPLE_TRIAL } from "../api/sample";
import type { ApiError } from "../types/canonical";

/**
 * The entry console.
 *
 * A judge meets this screen first, so it has one job beyond starting a
 * screening: say what the product does before anyone clicks. The claim is the
 * chain — a record becomes an eligibility decision, the decision carries its
 * evidence, a person signs it, and the same participant continues into
 * monitoring — so the chain itself is the illustration rather than a stock
 * graphic bolted on beside it.
 *
 * Every number here is derived from the sample data the demo actually screens.
 * Nothing is a marketing figure: rule coverage is counted from SAMPLE_TRIAL's
 * own criteria, and the case preview reads SAMPLE_PATIENT.
 */

interface Props {
  onFile: (file: File) => void;
  onUseSample: () => void;
  busy: boolean;
  error: ApiError | null;
}

/** The stages a record passes through, and where Phase 1 hands over. */
const STAGES = [
  { label: "Patient data", note: "record parsed to canonical schema" },
  { label: "Eligibility", note: "deterministic rules, per criterion" },
  { label: "Evidence", note: "every verdict cites its source" },
  { label: "Review", note: "a named person decides" },
  { label: "Phase 2", note: "enrolment and administration" },
  { label: "Monitoring", note: "risk, protocol, investigator" },
];

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

  // Counted from the trial the demo actually screens, so it cannot drift.
  const expressible = SAMPLE_TRIAL.criteria.filter((c) => c.rule !== null).length;
  const total = SAMPLE_TRIAL.criteria.length;
  const coverage = Math.round((expressible / total) * 100);

  return (
    <div className="space-y-8">
      {/* -- hero ------------------------------------------------------- */}
      <section className="grid items-start gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <div className="animate-rise">
          <div className="eyebrow">Clinical trial intelligence</div>

          <h1 className="title mt-3 text-[clamp(1.9rem,4vw,2.8rem)]">
            Screen candidates.
            <br />
            Verify the evidence.
            <br />
            <span className="text-ink-mid">Continue into monitoring.</span>
          </h1>

          <p className="mt-4 max-w-xl font-sans text-[15px] leading-relaxed text-ink-mid">
            TrialGuard AI turns fragmented clinical records into traceable
            eligibility decisions, then carries the same participant into
            protocol monitoring — with the reasoning kept visible at every step.
          </p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
              className="border border-ink bg-ink px-5 py-2.5 font-sans text-[13px] font-semibold text-paper transition-colors hover:border-signal-deep hover:bg-signal-deep disabled:cursor-not-allowed disabled:opacity-40"
            >
              Upload clinical record
            </button>
            <button
              type="button"
              onClick={onUseSample}
              disabled={busy}
              className="border border-rule-strong px-5 py-2.5 font-sans text-[13px] font-medium transition-colors hover:border-ink disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? "Screening…" : "Run demo candidate"}
            </button>
          </div>

          <p className="mt-3 font-sans text-[11.5px] text-ink-faint">
            The demo runs the real Phase 1 engine on the sample record below.
            Nothing on this screen is mocked.
          </p>
        </div>

        <WorkflowChain />
      </section>

      {/* -- instrument strip -------------------------------------------- */}
      <section
        aria-label="Screening context"
        className="grid gap-px border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-4"
      >
        <Instrument label="Active trial" value={SAMPLE_TRIAL.trial_id} mono />
        <Instrument label="Monitoring protocol" value="DEMO-PROTOCOL-1" mono />
        <Instrument label="Screening mode" value="Rules authoritative" />
        <Instrument label="Evidence" value="Traceable to source" />
      </section>

      {/* -- intake and the case it will run ----------------------------- */}
      <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,21rem)]">
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
          className={`flex min-h-[13rem] flex-col justify-center border-2 border-dashed p-8 transition-colors ${
            dragging ? "border-signal bg-signal-wash" : "border-rule-strong bg-panel"
          }`}
        >
          {busy ? (
            <Processing />
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4">
              <div>
                <div className="eyebrow">Structured clinical record</div>
                <p className="mt-1.5 font-sans text-[15px] text-ink">
                  {dragging ? "Release to read this record" : "Drop a file here"}
                </p>
                <p className="mt-1 font-sans text-[12px] text-ink-faint">
                  Text-based PDF. Parsed into the canonical schema, then screened
                  by the same engine the demo uses.
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] tracking-[0.08em] text-ink-faint">
                  <span>PDF SUPPORTED</span>
                  <span aria-hidden className="h-2.5 w-px bg-rule" />
                  <span>NO FILE LEAVES THIS MACHINE</span>
                </div>
              </div>

              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                className="border border-ink px-4 py-2 font-sans text-[13px] font-medium transition-colors hover:bg-ink hover:text-paper"
              >
                Select PDF
              </button>
            </div>
          )}

          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            onChange={(e) => accept(e.target.files?.[0] ?? undefined)}
          />
        </div>

        <DemoCase onRun={onUseSample} busy={busy} />
      </section>

      {(error || localError) && (
        <ErrorNotice error={error} localMessage={localError} />
      )}

      {/* -- what makes the verdict trustworthy --------------------------- */}
      <section className="grid gap-x-10 gap-y-6 border-t border-rule pt-6 sm:grid-cols-3">
        <Claim headline={`${coverage}%`} label="Rule coverage">
          {expressible} of {total} criteria in {SAMPLE_TRIAL.trial_id} are
          expressible as deterministic rules. The rest are referred, not guessed.
        </Claim>
        <Claim headline="Pass / Fail / Unknown" label="Explicit uncertainty" small>
          Anything the record cannot support is held as UNKNOWN rather than
          resolved by inference.
        </Claim>
        <Claim headline="Human review" label="AI never overrides rules" small>
          The advisory layer can flag a conflict with the engine. It cannot
          change a verdict.
        </Claim>
      </section>

      {/* -- lifecycle spine ---------------------------------------------- */}
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-2 border-t border-rule pt-4">
        {["Screen", "Verify", "Review", "Monitor"].map((step, index) => (
          <li key={step} className="flex items-center gap-2">
            <span
              className={`readout text-[10px] ${
                index === 0 ? "text-signal-deep" : "text-ink-faint"
              }`}
            >
              {String(index + 1).padStart(2, "0")}
            </span>
            <span
              className={`text-[11px] tracking-[0.12em] ${
                index === 0 ? "font-semibold text-ink" : "text-ink-faint"
              }`}
            >
              {step.toUpperCase()}
            </span>
            {index < 3 && (
              <span aria-hidden className="mx-2 h-px w-8 bg-rule sm:w-12" />
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * The chain, drawn. Six stages on one spine, the way the timeline and the
 * trajectory draw theirs — so the entry screen already speaks the console's
 * visual language. The first node is filled because that is where the reader
 * is standing.
 */
function WorkflowChain() {
  const TOP = 16;
  const STEP = 56;
  const height = TOP + (STAGES.length - 1) * STEP + 28;
  const spineEnd = TOP + (STAGES.length - 1) * STEP;
  // Phase 1 owns the first four stages; the hand-over sits after Review.
  const handover = TOP + 3 * STEP + STEP / 2;

  return (
    <svg
      viewBox={`0 0 320 ${height}`}
      className="w-full max-w-[20rem]"
      role="img"
      aria-label="How a record moves through TrialGuard: patient data, eligibility, evidence, review, phase 2, monitoring"
    >
      <line
        x1="14"
        y1={TOP}
        x2="14"
        y2={spineEnd}
        stroke="var(--color-rule-strong)"
        strokeWidth="1"
        className="animate-draw"
        style={{ "--draw-length": String(spineEnd - TOP) } as React.CSSProperties}
      />

      <line
        x1="0"
        y1={handover}
        x2="320"
        y2={handover}
        stroke="var(--color-rule)"
        strokeWidth="1"
        strokeDasharray="3 4"
      />
      <text
        x="320"
        y={handover - 6}
        textAnchor="end"
        className="fill-ink-faint font-mono"
        fontSize="8.5"
        letterSpacing="0.1em"
      >
        PHASE 1 · PHASE 2
      </text>

      {STAGES.map((stage, index) => {
        const y = TOP + index * STEP;
        const first = index === 0;
        return (
          <g
            key={stage.label}
            className="animate-rise"
            style={{ animationDelay: `${index * 70}ms` }}
          >
            <rect
              x={first ? 8 : 9.5}
              y={first ? y - 6 : y - 4.5}
              width={first ? 12 : 9}
              height={first ? 12 : 9}
              fill={first ? "var(--color-signal)" : "var(--color-panel)"}
              stroke={first ? "var(--color-signal-deep)" : "var(--color-rule-strong)"}
              strokeWidth="1.5"
            />
            <text
              x="34"
              y={y + 1}
              className="fill-ink font-sans"
              fontSize="13"
              fontWeight="600"
            >
              {stage.label}
            </text>
            <text x="34" y={y + 16} className="fill-ink-faint font-sans" fontSize="11">
              {stage.note}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function Instrument({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="bg-panel px-4 py-3">
      <div className="eyebrow">{label}</div>
      <div className={`mt-1 text-[15px] font-medium ${mono ? "readout" : "font-sans"}`}>
        {value}
      </div>
    </div>
  );
}

/** The case the demo button will actually screen, read from the sample data. */
function DemoCase({ onRun, busy }: { onRun: () => void; busy: boolean }) {
  return (
    <aside className="animate-rise border border-rule bg-panel">
      <div className="border-b border-rule px-4 py-3">
        <div className="eyebrow">Demo candidate</div>
        <div className="readout mt-1 text-[22px] font-semibold leading-none">
          {SAMPLE_PATIENT.patient_id}
        </div>
        <div className="mt-1.5 font-sans text-[12px] text-ink-mid">
          {SAMPLE_PATIENT.age} years · {SAMPLE_PATIENT.sex.toLowerCase()} · screened
          against <span className="readout">{SAMPLE_TRIAL.trial_id}</span>
        </div>
      </div>

      <dl className="grid grid-cols-3 gap-px bg-rule">
        <Figure label="Conditions" value={SAMPLE_PATIENT.conditions.length} />
        <Figure label="Medications" value={SAMPLE_PATIENT.medications.length} />
        <Figure label="Lab results" value={SAMPLE_PATIENT.labs.length} />
      </dl>

      <div className="border-t border-rule px-4 py-3">
        <div className="eyebrow mb-1.5">What happens</div>
        <p className="font-sans text-[12px] leading-relaxed text-ink-mid">
          {SAMPLE_TRIAL.criteria.length} criteria are checked, each with its
          evidence. The result needs a human decision before Phase 2.
        </p>
        <button
          type="button"
          onClick={onRun}
          disabled={busy}
          className="mt-3 font-sans text-[12px] font-medium text-signal-deep underline underline-offset-4 transition-opacity hover:text-ink disabled:opacity-40"
        >
          {busy ? "Screening…" : "Run this candidate →"}
        </button>
      </div>
    </aside>
  );
}

function Figure({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-panel px-3 py-2.5">
      <dt className="text-[10px] tracking-[0.08em] text-ink-faint">
        {label.toUpperCase()}
      </dt>
      <dd className="readout mt-0.5 text-[17px] font-semibold leading-none">{value}</dd>
    </div>
  );
}

function Claim({
  headline,
  label,
  small,
  children,
}: {
  headline: string;
  label: string;
  small?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div
        className={
          small
            ? "title text-[17px]"
            : "readout text-[34px] font-semibold leading-none"
        }
      >
        {headline}
      </div>
      <div className="eyebrow mt-1.5">{label}</div>
      <p className="mt-2 font-sans text-[12px] leading-relaxed text-ink-mid">
        {children}
      </p>
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
      <div className="relative mb-4 h-0.5 w-full max-w-xs overflow-hidden bg-band">
        <div className="animate-sweep absolute inset-y-0 w-1/4 bg-signal" />
      </div>
      <div className="eyebrow mb-3">Screening in progress</div>
      {/* The pipeline, arriving in the order it actually runs. */}
      <ol className="stagger flex flex-col gap-1.5">
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
    <div className="border border-alert/35 bg-alert-wash p-4">
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
