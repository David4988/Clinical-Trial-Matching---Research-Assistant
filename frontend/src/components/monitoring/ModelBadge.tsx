import type { ModelProvenance } from "../../types/monitoring";

/**
 * What produced the risk numbers on this screen.
 *
 * The point of this component is that "LIVE" is not a decoration: it is
 * rendered from `live_inference`, which the backend sets only when the loaded
 * provider actually performs inference from a serialized artifact. A
 * deterministic provider says so plainly instead. Nothing here is hardcoded —
 * the name, version and checksum all come from the artifact's own metadata,
 * and the pulse stops when the inference does.
 */

const DESCRIPTIONS: Record<string, string> = {
  synthetic_ml: "Isolation Forest, scoring each observation window as it arrives",
  synthetic: "Replay of precomputed research fixtures",
  mock: "Deterministic rule-based provider, no model loaded",
};

export function ModelBadge({ model }: { model: ModelProvenance }) {
  const live = model.live_inference;
  const artifact = model.artifact;

  return (
    <section
      aria-label="Risk model provenance"
      className="border border-rule bg-panel"
    >
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-2.5">
          {live ? (
            <span className="relative flex h-2.5 w-2.5 shrink-0" aria-hidden>
              <span className="animate-live absolute inline-flex h-full w-full rounded-full bg-signal" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-signal-deep" />
            </span>
          ) : (
            <span
              className="hatch h-2.5 w-2.5 shrink-0 border border-rule-strong"
              aria-hidden
            />
          )}
          <div>
            <div
              className={`text-[10px] font-semibold tracking-[0.14em] ${
                live ? "text-signal-deep" : "text-ink-faint"
              }`}
            >
              {live ? "LIVE MODEL" : "DETERMINISTIC"}
            </div>
            <div className="readout text-[15px] font-medium leading-tight">
              {model.model_version}
            </div>
          </div>
        </div>

        <div className="hidden h-8 w-px bg-rule sm:block" aria-hidden />

        <p className="min-w-[14rem] flex-1 font-sans text-[12px] leading-relaxed text-ink-mid">
          {DESCRIPTIONS[model.provider] ?? "Risk provider loaded at startup."}
          <span className="text-ink-faint"> · {model.provider}</span>
        </p>

        {artifact?.model_sha256 && (
          <div className="text-right">
            <div className="eyebrow">Artifact</div>
            <div className="readout text-[11px] text-ink-mid">
              {artifact.model_sha256.slice(0, 12)}
            </div>
          </div>
        )}
      </div>

      {artifact && (
        <details className="group border-t border-rule px-4 py-2">
          <summary className="inline-flex items-center gap-1.5 text-[11px] text-ink-mid hover:text-ink">
            <span className="transition-transform duration-200 group-open:rotate-90">▸</span>
            Artifact provenance
          </summary>
          <dl className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
            <Row label="Estimator" value={artifact.estimator?.class} />
            <Row label="Feature version" value={artifact.feature_version} />
            <Row label="Training cohort" value={cohortSummary(artifact.training_cohort)} />
            <Row label="Scoring" value={artifact.scoring?.anomaly_score} />
            <Row
              label="Features"
              value={artifact.features ? `${artifact.features.length}` : null}
            />
            <Row
              label="Built"
              value={
                artifact.created_at
                  ? new Date(artifact.created_at).toLocaleString()
                  : null
              }
            />
            <Row label="SHA-256" value={artifact.model_sha256} />
          </dl>
          {artifact.features && (
            <p className="mt-2 font-sans text-[11px] leading-relaxed text-ink-faint">
              {artifact.features.join(" · ")}
            </p>
          )}
        </details>
      )}

      {model.artifact_error && (
        <p className="border-t border-rule px-4 py-2 font-sans text-[11px] text-ink-mid">
          Artifact metadata unavailable: {model.artifact_error}
        </p>
      )}
    </section>
  );
}

/** The cohort the artifact was fitted on, as one readable line. */
function cohortSummary(
  cohort: NonNullable<ModelProvenance["artifact"]>["training_cohort"],
): string | null {
  if (!cohort) return null;
  const parts = [
    cohort.total_patients != null && `${cohort.total_patients} patients`,
    cohort.fitted_rows != null && `${cohort.fitted_rows} rows fitted`,
    cohort.source,
  ].filter((part): part is string => typeof part === "string");
  return parts.length > 0 ? parts.join(" · ") : null;
}

/**
 * Renders scalars only. Artifact metadata is free-form JSON the model owns, so
 * a field that becomes an object must degrade to a hidden row rather than
 * throwing "Objects are not valid as a React child" and blanking the page.
 */
function Row({ label, value }: { label: string; value: unknown }) {
  if (typeof value !== "string" && typeof value !== "number") return null;
  if (value === "") return null;
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-[10px] tracking-[0.08em] text-ink-faint">{label}</dt>
      <dd className="readout break-all text-[11px]">{value}</dd>
    </div>
  );
}
