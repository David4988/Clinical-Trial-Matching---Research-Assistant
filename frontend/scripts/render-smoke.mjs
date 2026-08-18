/**
 * Server-render the monitoring provenance badge against the payload the
 * backend actually serves.
 *
 * `tsc` cannot catch this class of bug: the artifact fields arrive as nested
 * JSON objects, and a component that renders one as a React child throws at
 * runtime and unmounts the whole app — a blank Monitoring tab, with a clean
 * typecheck and a clean build. Rendering it once here is the only check that
 * sees it.
 *
 * Run: npm run smoke:render
 */

import { build } from "esbuild";
import { createRequire } from "node:module";
import { mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

/** Mirrors GET /monitoring/model under RISK_PROVIDER=synthetic_ml. */
const LIVE_MODEL = {
  provider: "synthetic_ml",
  model_version: "synthetic_if_v1",
  live_inference: true,
  artifact: {
    model_version: "synthetic_if_v1",
    feature_version: "synthetic_features_v1",
    features: [
      "heart_rate",
      "spo2",
      "respiratory_rate",
      "heart_rate_delta",
      "spo2_delta",
      "respiratory_rate_delta",
    ],
    estimator: {
      class: "sklearn.ensemble.IsolationForest",
      n_estimators: 100,
      contamination: 0.1,
      random_state: 42,
    },
    training_cohort: {
      source: "synthetic_trial/data/observations.csv",
      scenarios: ["STABLE", "IMPROVING"],
      total_patients: 500,
      cohort_windows: 14688,
      fitted_rows: 14586,
    },
    scoring: {
      anomaly_score: "negated_decision_function",
      decimals: 6,
    },
    created_at: "2026-08-17T06:35:20.456684+00:00",
    model_sha256:
      "8114caf6302beebe09d3e107a913ce27530c3d062862d98612df4e08e5f641a2",
    trained_with: { python: "3.14.5", sklearn: "1.9.0" },
  },
};

/** A deterministic provider reports no artifact at all. */
const MOCK_MODEL = {
  provider: "mock-risk-v1",
  model_version: "mock-risk-v1",
  live_inference: false,
};

const entry = `
import { renderToString } from "react-dom/server";
import { ModelBadge } from ${JSON.stringify(
  resolve(root, "src/components/monitoring/ModelBadge.tsx"),
)};

export function render(model) {
  return renderToString(<ModelBadge model={model} />);
}
`;

// Built into the package so `react`/`react-dom` resolve normally, then removed.
const outfile = resolve(root, "node_modules/.cache/render-smoke/badge.cjs");
mkdirSync(dirname(outfile), { recursive: true });

await build({
  stdin: { contents: entry, resolveDir: root, loader: "tsx" },
  bundle: true,
  outfile,
  platform: "node",
  format: "cjs",
  jsx: "automatic",
  packages: "external",
  logLevel: "error",
});

const require = createRequire(import.meta.url);
const { render } = require(outfile);
rmSync(dirname(outfile), { recursive: true, force: true });

const cases = [
  ["synthetic_ml (live artifact)", LIVE_MODEL],
  ["mock (no artifact)", MOCK_MODEL],
];

let failed = false;
for (const [label, model] of cases) {
  try {
    const html = render(model);
    if (html.includes("[object Object]")) {
      throw new Error("an object reached the DOM as text");
    }
    console.log(`  ok   ${label}`);
  } catch (error) {
    failed = true;
    console.error(`  FAIL ${label}: ${error.message}`);
  }
}

if (failed) {
  console.error("\nrender smoke failed");
  process.exit(1);
}
console.log("\nrender smoke passed");
