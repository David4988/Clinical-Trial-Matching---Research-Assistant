import { useState } from "react";
import type { ApiError } from "../types/canonical";
import type { TreatmentAssignment } from "../types/monitoring";

/**
 * Phase 2 administration: the participant is enrolled, and a clinician records
 * what was actually given.
 *
 * Scope is deliberately narrow. This records an administration that a human
 * performed; it does not schedule, stock, calculate or approve one. The lifecycle
 * strip across the top is the whole state machine — there is no other status
 * this screen can produce.
 */

type Stage = "enrolled" | "administered" | "monitoring";

export function AdministrationPanel({
  treatment,
  busy,
  error,
  onAdminister,
  onOpenMonitoring,
}: {
  treatment: TreatmentAssignment;
  busy: boolean;
  error: ApiError | null;
  onAdminister: (dose: {
    amount: number;
    unit: string;
    route: string;
    administered_by: string;
  }) => void;
  onOpenMonitoring: () => void;
}) {
  const [amount, setAmount] = useState("5");
  const [unit, setUnit] = useState("mg");
  const [route, setRoute] = useState("IV");
  const [by, setBy] = useState("");

  const latest = treatment.doses[treatment.doses.length - 1] ?? null;
  const stage: Stage = latest ? "administered" : "enrolled";
  const parsed = Number(amount);
  const ready = Number.isFinite(parsed) && parsed > 0 && unit.trim() !== "" && by.trim() !== "";

  return (
    <section aria-labelledby="administration-heading" className="animate-rise space-y-4">
      {/* Continuity, stated once: the same person crosses the boundary. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-l-2 border-signal bg-signal-wash px-3 py-2">
        <span className="text-[10px] font-semibold tracking-[0.12em] text-signal-deep">
          PHASE 1 → PHASE 2
        </span>
        <span className="font-sans text-[12px] text-ink">
          <span className="readout">{treatment.patient_id}</span> is enrolled on{" "}
          <span className="readout">{treatment.trial_id}</span> — same participant,
          same trial, now a treatment record.
        </span>
      </div>

      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="administration-heading" className="title text-[19px]">
          Administration
        </h2>
        <span className="readout text-[11px] text-ink-faint">
          treatment {treatment.treatment_id}
        </span>
      </div>

      <Lifecycle stage={stage} />

      <div className="grid gap-px border border-rule bg-rule sm:grid-cols-3">
        <Cell label="Participant" value={treatment.patient_id} />
        <Cell label="Trial" value={treatment.trial_id} />
        <Cell label="Drug" value={treatment.drug_name} />
      </div>

      {latest ? (
        <div className="border border-rule bg-panel">
          <div className="h-1.5 bg-ink" />
          <div className="p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-[13px] font-semibold tracking-[0.08em]">
                DOSE {latest.dose_number} ADMINISTERED
              </span>
              <span className="text-[11px] text-ink-faint">
                {new Date(latest.administered_at).toLocaleString()}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
              <span className="tabular-nums">
                {latest.amount} {latest.unit}
              </span>
              {latest.route && <span>{latest.route}</span>}
              {latest.administered_by && (
                <span className="text-ink-mid">{latest.administered_by}</span>
              )}
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-rule pt-4">
              <button
                type="button"
                onClick={onOpenMonitoring}
                className="border border-ink bg-ink px-5 py-2.5 text-[13px] font-semibold text-paper transition-colors hover:border-signal-deep hover:bg-signal-deep"
              >
                Open monitoring →
              </button>
              <span className="font-sans text-[11px] text-ink-faint">
                Continued monitoring begins from this administration.
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="border border-rule bg-panel p-4">
          <div className="eyebrow mb-3">Record administration</div>

          <div className="grid gap-4 sm:grid-cols-4">
            <Field id="dose-amount" label="Dose" value={amount} onChange={setAmount} inputMode="decimal" />
            <Field id="dose-unit" label="Unit" value={unit} onChange={setUnit} />
            <Field id="dose-route" label="Route" value={route} onChange={setRoute} />
            <Field
              id="dose-by"
              label="Administered by"
              placeholder="Name"
              value={by}
              onChange={setBy}
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
              onClick={() =>
                onAdminister({
                  amount: parsed,
                  unit: unit.trim(),
                  route: route.trim(),
                  administered_by: by.trim(),
                })
              }
              className="border border-ink bg-ink px-4 py-2 text-[12px] font-medium text-paper hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-30"
            >
              {busy ? "Recording…" : "Record administration"}
            </button>
            <span className="font-sans text-[11px] leading-relaxed text-ink-faint">
              Records a dose a clinician has already given. This system does not
              administer treatment.
            </span>
          </div>
        </div>
      )}
    </section>
  );
}

function Lifecycle({ stage }: { stage: Stage }) {
  const steps: { key: Stage; label: string }[] = [
    { key: "enrolled", label: "Enrolled" },
    { key: "administered", label: "Administered" },
    { key: "monitoring", label: "Monitoring" },
  ];
  const active = steps.findIndex((step) => step.key === stage);

  return (
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {steps.map((step, index) => {
        const done = index <= active;
        return (
          <li key={step.key} className="flex items-center gap-3">
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className={`inline-block h-2.5 w-2.5 ${
                  done ? "bg-ink" : "hatch border border-rule-strong"
                }`}
              />
              <span
                className={`text-[11px] tracking-[0.08em] ${
                  done ? "text-ink" : "text-ink-faint"
                }`}
              >
                {step.label.toUpperCase()}
              </span>
            </span>
            {index < steps.length - 1 && (
              <span aria-hidden className="h-px w-6 bg-rule-strong" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-panel p-3">
      <div className="eyebrow">{label}</div>
      <div className="mt-1 text-[15px] font-medium">{value}</div>
    </div>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  inputMode,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  inputMode?: "decimal";
}) {
  return (
    <div>
      <label htmlFor={id} className="eyebrow mb-1 block">
        {label}
      </label>
      <input
        id={id}
        type="text"
        inputMode={inputMode}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full border border-rule-strong bg-paper px-3 py-2 font-sans text-[13px] text-ink placeholder:text-ink-faint focus:border-ink focus:outline-none"
      />
    </div>
  );
}
