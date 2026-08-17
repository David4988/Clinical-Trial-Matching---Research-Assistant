# Live ML inference

The Phase 2 risk layer can be answered by a **trained Isolation Forest scoring
the monitoring window that just arrived** — not by a precomputed fixture.

```
POST /monitoring/observations       one window: HR, SpO2, RR (+ whatever else)
        ↓
POST /monitoring/patients/{id}/cycle
        ↓
PatientState                        deterministic, recomputed on read
        ↓
PatientWindowState                  current window + the one before it
        ↓
six features                        3 values + 3 deltas, fixed order
        ↓
IsolationForest                     loaded from disk, never refitted
        ↓
deterministic evidence + explanation
        ↓
RiskAssessment                      the existing schema, unchanged
        ↓
trust gate → protocol → next dose → dashboard
```

## Three providers, one interface

| `RISK_PROVIDER` | Class | What answers |
| --- | --- | --- |
| `mock` *(default)* | `MockRiskProvider` | Protocol bands. No ML. |
| `synthetic` | `SyntheticArtifactProvider` | Three precomputed research cases from `synthetic_demo_cases.json`, matched on the patient id. |
| `synthetic_ml` | `SyntheticMLProvider` | **Live inference** on the incoming window. |

`synthetic` and `synthetic_ml` are different things and are deliberately not
interchangeable. The first replays known cases and is for offline demos, UI work
and regression tests; it remains fully supported. The second loads the trained
artifact. `RiskAssessment.provider` records which one answered, so a stored cycle
always says.

```bash
RISK_PROVIDER=synthetic_ml python -m uvicorn app.main:app --port 8000
```

If the artifact or scikit-learn is missing, startup logs the reason and falls
back to `mock` rather than refusing to serve.

## The feature contract

Six features, in this exact order, no scaling, no preprocessing:

```
0  heart_rate               bpm, this window
1  spo2                     %,   this window
2  respiratory_rate         breaths/min, this window
3  heart_rate_delta         this window − previous window
4  spo2_delta               this window − previous window
5  respiratory_rate_delta   this window − previous window
```

Deltas are rounded to 4 decimals, matching `synthetic_trial/src/features.py`.

The order is declared as a tuple in two places —
`app/synthetic/inference/contract.py` and the artifact's metadata JSON — and the
engine refuses to load an artifact whose order differs. That check exists because
a permuted vector scores perfectly happily and is wrong everywhere.

Systolic BP, diastolic BP and temperature are ingested and used by the rest of
the system. The model never sees them.

## Temporal state: derived, not stored

The model needs the previous window, so something must remember it.

**It is derived from the observation store, not cached.** `PatientState` is
recomputed from observations on every read precisely so there is no stored
derived state to fall out of date; a `dict[patient_id, previous_window]` in the
risk layer would undo that. It would not survive a restart, would diverge between
workers, and would make a replayed demo produce different numbers the second
time.

`PatientWindowState.from_observations()` groups a patient's observations by
`recorded_at`, keeps the instants where **all three** model signals were
recorded, and takes the last two. Two properties then hold by construction rather
than by testing: no cross-patient leakage is possible, and the same record always
produces the same vector.

### The first window

A patient's first window has no predecessor, so three of the six features do not
exist.

**Nothing is fabricated.** No zero, no carry-forward, no population default. The
provider returns `level=UNKNOWN`, `score=0.0`, and says why in
`likely_patterns`. This mirrors the research pipeline, where `score_observations`
gives an unscoreable row a null score rather than a reassuring one, and it
mirrors the Phase 1 rule that an unevaluable check is never counted as passed.

That assessment is **not** marked `degraded`. `degraded` means the provider
failed; this is a working provider reporting that the record cannot yet support
a verdict. A missing artifact or an unexpected exception *is* `degraded`, and the
trust gate reports the two cases differently.

The same applies when a window is incomplete: if the previous instant is missing
SpO2, there is no delta and the window is not scored.

## From anomaly score to risk level

```
anomaly_score      = round(-model.decision_function(X), 6)     higher = worse
predicted_anomaly  = 1 when model.predict(X) == -1
```

| Level | Condition |
| --- | --- |
| RED | `predicted_anomaly == 1` — **the model's own call**, its boundary from `contamination=0.10` |
| AMBER | within `0.02` below that boundary — *synthetic* presentation band |
| GREEN | below that |

`RiskAssessment.score` projects the raw score onto `[0, 1]` with the decision
boundary landing on exactly `0.5`, so "above 0.5" and "the model flagged it" mean
the same thing on screen.

`confidence` is driven by data quality, not by the score. An Isolation Forest
returns no calibrated probability, so deriving confidence from how anomalous the
answer was would be inventing a number the model never produced.

The AMBER margin is the only invented constant in this path, it is marked
`SYNTHETIC` in the source, and it can only move a window from GREEN to AMBER — it
can never create or suppress a RED.

## Evidence

`app/synthetic/inference/evidence.py` builds the evidence object and the
deterministic explanation from **the live observation and the model's output**:
current HR / SpO2 / RR, all three deltas, the anomaly score, the predicted label,
the strongest signal, and the record's data quality.

`synthetic_demo_cases.json` is never opened on this path, and the patient's
trajectory label is never read. A test asserts both: identical physiology under
the patient ids `PT-demo-STABLE` and `PT-demo-ADVERSE_EVENT` produces one answer.

### Optional narration

`SyntheticMLProvider(narrator=…)` accepts a callable that receives the finished
evidence and explanation and returns extra advisory lines for `likely_patterns`.
A Gemini call can go here. It is **off by default and the application works
without it**; the assessment is already complete before it runs, so it cannot
influence the score, the level, the state, or any physiological value, and a
narrator that raises is logged and skipped.

## Regenerating and deploying the artifact

In the research repository:

```bash
.venv/bin/python train_model_artifact.py        # fit + serialise + self-verify
.venv/bin/python export_inference_fixtures.py   # refresh the parity fixture
```

Then copy the pair across:

```bash
cp synthetic_trial/artifacts/synthetic_isolation_forest.{joblib,json} \
   ../Clinical-Trial-Matching---Research-Assistant/backend/app/synthetic/artifacts/
```

And verify in this repository:

```bash
cd backend
.venv/bin/python -m pytest tests/test_research_parity.py -q   # research == app
.venv/bin/python scripts/live_inference_demo.py               # three live windows
```

`train_model_artifact.py` reloads what it just wrote and refuses to finish unless
the reloaded model reproduces the fitted model's scores exactly.

## End-to-end trajectory validation

A held-out patient is replayed through the live HTTP endpoints, window by
window, at the 5-minute cadence the model was trained on:

```bash
cd backend
.venv/bin/python scripts/live_trajectory_demo.py                 # around the transition
.venv/bin/python scripts/live_trajectory_demo.py --all --compact # all 144 windows
```

`P0014` — evaluation half, `SUDDEN_DETERIORATION`, ground-truth change point at
window 103, exported unmodified by `export_inference_fixtures.py`. Each window is
`POST`ed to `/monitoring/observations` and evaluated by
`/monitoring/patients/{id}/cycle`; nothing calls the model or the provider
directly.

```
 win   time      HR   SpO2     RR      ΔHR   ΔSpO2     ΔRR       score    pred  risk
  96  06:00    83.7   95.6   14.2        —       —       —           —       —  UNKNOWN
  97  06:05    77.7   94.3   14.9     -6.0    -1.3    +0.7   -0.040291  NORMAL  GREEN
  ...
 102  06:30    82.6   94.6   17.4     +1.9    +0.2    +3.3   -0.075542  NORMAL  GREEN
 103 *06:35    99.3   90.4   22.5    +16.7    -4.2    +5.1   +0.212998 ANOMALY  RED
 104  06:40   101.5   89.8   22.3     +2.2    -0.6    -0.2   +0.071445 ANOMALY  RED
  ...
 126  08:30    98.3   89.7   21.7     -5.5    -0.5    +0.9   +0.072007 ANOMALY  RED

effective risk path     UNKNOWN×1 -> GREEN×6 -> RED×24
before change point       6 windows,   0% flagged by the model
after change point       24 windows, 100% flagged by the model
```

The model flags at window 103 — the ground-truth change point — with **zero
detection delay**, and holds. Windows 104 onward carry small deltas but stay
anomalous because HR ≈ 100 / SpO₂ ≈ 90 / RR ≈ 23 are themselves unusual against
the STABLE + IMPROVING cohort: the vector's level half and delta half both do
work.

None of that sequence is asserted literally in the tests. They assert the
*shape* — that the flag rate rises across the change point, that a transition is
recorded, that the flagged run is sustained — and let the model supply the
numbers.

### Downstream, verified rather than assumed

| Mechanism | Observed |
| --- | --- |
| Trust gate | Silent on this record — quality is `OK`, so `provider_level == level` on every scored window, `gated = 0` |
| Transition | `First assessment: UNKNOWN` → `De-escalated to GREEN` → `Escalated from GREEN to RED` |
| Protocol | GREEN → `ROUTINE_MONITORING`; RED → `URGENT_ESCALATION`, `NOTIFY_CLINICIAN`, `INCREASE_MONITORING` |
| Next dose | `HOLD` / `REVIEW_REQUIRED` on every RED window — the intentional block, confirmed firing |
| Cycle continuity | RED is not terminal; later windows still ingest and still cycle |
| Timeline | `OBSERVATIONS_INGESTED`, `RISK_ASSESSED`, `RISK_TRANSITION`, `INTERVENTION_RAISED`, `NEXT_DOSE_ASSESSED`, all naming `synthetic_ml` |

### Static vs live, side by side

Replaying the *same* windows under `RISK_PROVIDER=synthetic` and
`RISK_PROVIDER=synthetic_ml` with the patient id `PT-demo-SUDDEN_DETERIORATION`:
the static provider returns **one level for all 31 windows** because it reads the
id, while the live provider's level moves with the physiology. Both remain
functional; a test asserts the contrast.

## What is checked

- `tests/synthetic/test_inference_windows.py` — deltas, patient boundaries, first
  window, ordering, state advancing.
- `tests/synthetic/test_inference_engine.py` — artifact present, metadata matches
  the estimator, reload determinism, refusal of a reordered or tampered artifact.
- `tests/risk/test_synthetic_ml_provider.py` — schema, provenance, live input,
  never raises, the static JSON is never opened.
- `tests/test_research_parity.py` — 56 evaluation windows across all seven
  scenarios, feature-by-feature and score-by-score against the research pipeline.
- `tests/test_live_trajectory_e2e.py` — one held-out patient replayed over HTTP:
  ingestion, transition, protocol response, dose hold, timeline, dashboard
  payload, static-vs-live contrast, full-trajectory parity, and the edge cases
  below.
- `tests/risk/test_synthetic_provider.py` — the static provider, unchanged.

### Edge cases covered

| Case | Behaviour |
| --- | --- |
| First window | Not scored, `UNKNOWN`, `degraded = False`, no delta invented |
| Second patient, one window | Stays `UNKNOWN` even with physiology that scored RED for another patient — no inherited predecessor |
| Signal missing from an instant | The instant is dropped rather than patched; the older reading is never reused to manufacture a delta. Data quality stays `OK` if that signal is merely recent-but-not-current, so the *provider* declines while the gate correctly stays silent |
| Out-of-order arrival | Reconciled by `recorded_at`, not arrival order. A late window becomes the predecessor it should have been and the delta corrects (`+18` → `+16`). Existing behaviour, confirmed, not changed |

## Known caveats

**Sampling cadence.** The model was fitted on 5-minute windows. `delta` means
"change since the previous window" in both repositories, but a demo generated at
15-minute intervals produces roughly 3× larger deltas for the same underlying
trend, which shifts scores upward. The live demo uses 5-minute spacing.

**Interpreter split.** The research repository runs Python 3.14; the application
runs 3.11, because `pydantic==2.10.4` has no 3.14 wheel. Both use
`scikit-learn==1.9.0`, which is the version that matters for unpickling. Parity
is verified empirically rather than assumed — see below.

**Research evidence bug, not reproduced here.** `synthetic_trial/src/evidence.py`
reads a `data_quality_label` column its generator never writes (the column is
`data_quality`), so every research evidence object reports `GOOD` and the
research explainer can never reach its `data_gap` branch. This touches no model
feature and no score. The application uses its own `DataQuality` instead.

## Parity result

Two independent comparisons, both against the research pipeline, both on data
never seen during fitting:

| | Sampled windows | Full trajectory |
| --- | --- | --- |
| Source | 56 windows, all 7 scenarios | `P0014`, all 143 scoreable windows |
| Worst feature drift | `0.000e+00` | `0.000e+00` |
| Worst anomaly-score drift | `0.000e+00` | `0.000e+00` |
| Label disagreements | 0 / 56 | 0 / 143 |

Bit-for-bit identical across the two interpreters, for isolated windows and for
an entire patient's history in sequence.
