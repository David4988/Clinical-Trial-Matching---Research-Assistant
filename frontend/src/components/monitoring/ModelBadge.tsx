import type { ModelProvenance } from "../../types/monitoring";

/**
 * What produced the risk numbers on this screen.
 *
 * The point of this component is that "LIVE" is not a decoration: it is
 * rendered from `live_inference`, which the backend sets only when the loaded
 * provider actually performs inference from a serialized artifact. A
 * deterministic provider says so plainly instead. Nothing here is hardcoded —
 * the name, version and checksum all come from the artifact's own metadata.
 */

const DESCRIPTIONS: Record<string, string> = {
  synthetic_ml: "Isolation Forest · live inference from the serialized artifact",
  synthetic: "Replay of precomputed research fixtures",
  mock: "Deterministic rule-based provider · no model loaded",
};

export function ModelBadge({ model }: { model: ModelProvenance }) {
  const live = model.live_inference;
  const artifact = model.artifact;

  return (
    <section
      aria-label="Risk model provenance"
      className="border border-rule bg-panel"
    >
      <div className={live ? "h-1 bg-ink" : "hatch h-1"} />
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
        <div>
          <div className="eyebrow">Provider</div>
          <div className="mt-0.5 text-[13px] font-medium">{model.provider}</div>
        </div>

        <div>
          <div className="eyebrow">Model</div>
          <div className="mt-0.5 text-[13px] font-medium">{model.model_version}</div>
        </div>

        <div>
          <div className="eyebrow">Inference</div>
          <div className="mt-0.5 flex items-center gap-1.5">
            <span
              aria-hidden
              className={`inline-block h-2.5 w-2.5 ${
                live ? "bg-ink" : "hatch border border-rule-strong"
              }`}
            />
            <span className="text-[13px] font-medium">
              {live ? "LIVE" : "DETERMINISTIC"}
            </span>
          </div>
        </div>

        <p className="min-w-[12rem] flex-1 font-sans text-[11px] leading-relaxed text-ink-faint">
          {DESCRIPTIONS[model.provider] ?? "Risk provider loaded at startup."}
          {artifact?.estimator && ` · ${artifact.estimator}`}
        </p>
      </div>

      {artifact && (
        <details className="group border-t border-rule px-3 py-2">
          <summary className="inline-flex items-center gap-1.5 text-[11px] text-ink-mid hover:text-ink">
            <span className="transition-transform group-open:rotate-90">▸</span>
            Artifact provenance
          </summary>
          <dl className="mt-2 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
            <Row label="Feature version" value={artifact.feature_version} />
            <Row label="Training cohort" value={artifact.training_cohort} />
            <Row label="Scoring" value={artifact.scoring} />
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
            <Row label="SHA-256" value={artifact.model_sha256?.slice(0, 16) ?? null} />
          </dl>
          {artifact.features && (
            <p className="mt-2 font-sans text-[11px] leading-relaxed text-ink-faint">
              {artifact.features.join(" · ")}
            </p>
          )}
        </details>
      )}

      {model.artifact_error && (
        <p className="border-t border-rule px-3 py-2 font-sans text-[11px] text-ink-mid">
          Artifact metadata unavailable: {model.artifact_error}
        </p>
      )}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline gap-2">
      <dt className="text-[10px] tracking-[0.08em] text-ink-faint">{label}</dt>
      <dd className="text-[11px]">{value}</dd>
    </div>
  );
}
