# Clinical Trial Matching & Research Assistant

Hexaware Premier League Mavericks Hackathon · PS4

**Phase 1** screens a patient against a trial protocol from a structured
clinical PDF. **Phase 2** monitors that patient through treatment and assesses
readiness for the next dose. Both explain every verdict they reach.

> Deterministic logic decides. In Phase 1 the rule engine is authoritative and
> the AI layer is advisory; in Phase 2 the protocol table is authoritative and
> the risk model is advisory. Anything that cannot be verified becomes
> `UNKNOWN` and goes to a human — it is never read as "probably fine".

---

## Quick start

Two terminals.

**Backend** (http://127.0.0.1:8000, docs at `/docs`)

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python scripts/generate_demo_pdf.py
python -m uvicorn app.main:app --reload --port 8000
```

**Frontend** (http://localhost:5173)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, upload `backend/fixtures/pdf/demo_screening.pdf`.

Open http://localhost:5173. **Screening** is Phase 1; switch to **Monitoring**
and press *Load demo cohort* for Phase 2.

## Verify

```bash
cd backend
.venv/Scripts/python -m pytest tests -q     # 310 tests, no network
.venv/Scripts/python scripts/smoke_test.py  # end-to-end against a running server
```

---

# Phase 2 — Treatment monitoring

An eligible patient enters treatment; observations arrive; the system tracks
their trajectory and advises on the next dose.

```
ELIGIBLE patient
  → treatment + dose registration
  → observation ingestion        (validated, never silently corrected)
  → PatientState                 DETERMINISTIC · derived, never stored
  → RiskProvider                 ADVISORY  → GREEN / AMBER / RED / UNKNOWN
  → data-quality trust gate      DETERMINISTIC · can force UNKNOWN
  → intervention engine          DETERMINISTIC · protocol table
  → next-dose assessment         PROCEED / REVIEW_REQUIRED / HOLD
  → dashboard + timeline
```

## The risk boundary

Phase 2 inverts Phase 1's trust model: the risk layer becomes the *primary*
signal driving clinical action. Three structural counterweights keep that safe.

**The model cannot express an action.** `RiskAssessment` has no field for an
intervention, a dose decision, or a recommendation — only a level, a score, and
its reasons. The protocol table in `monitoring/protocol.py` maps level → action,
and no provider can reach it. A test asserts the field list stays that way.

**The model can be overruled by data quality.** Before any action is chosen,
`monitoring/gate.py` asks whether the record can support a verdict at all. If
observations are missing or stale, the effective level becomes `UNKNOWN`
regardless of what the model said — and both levels are kept:

```
DATA-QUALITY GATE APPLIED
Risk model : GREEN
Applied    : UNKNOWN
SPO2 has no reading within the last 90 minutes.
```

`UNKNOWN` does **not** fall back to routine monitoring. It requests repeat
observations, alerts a clinician, and blocks `PROCEED`.

**The mock computes; it does not replay.** `MockRiskProvider` derives its level
from the actual measurements and trends in the `PatientState`, scored against
the demo protocol's bands. A deteriorating synthetic trajectory *causes* the
escalation — swap in a trained model and the rest of the system is unchanged.

## The trained model is now one of the providers

That swap has been made. `RISK_PROVIDER=synthetic_ml` answers the risk layer
with a **trained Isolation Forest scoring the window that just arrived** — six
features (HR, SpO2, RR and each one's change since the previous window), loaded
from a versioned artifact, never refitted in the application.

```bash
cd backend
RISK_PROVIDER=synthetic_ml python -m uvicorn app.main:app --port 8000
.venv/bin/python scripts/live_inference_demo.py     # three windows, live
```

```
  t      HR   SpO2     RR      ΔHR   ΔSpO2     ΔRR       score  flag  level
t0     70.0   98.0   15.0        —       —       —           —     —  UNKNOWN
t1     72.0   98.0   15.0       +2      +0      +0   -0.048674    no  GREEN
t2     88.0   94.0   21.0      +16      -4      +6   +0.152504   YES  RED
```

`t0` is UNKNOWN because a patient's first window has no predecessor, so three of
the six features do not exist — and none of them is invented. Nothing in that
table is scripted: the model produced every score.

Three providers now sit behind the one interface, and `RiskAssessment.provider`
records which answered:

| `RISK_PROVIDER` | What answers |
| --- | --- |
| `mock` *(default)* | Protocol bands, no ML |
| `synthetic` | Precomputed research fixtures, matched on patient id |
| `synthetic_ml` | Live inference on the incoming window |

### A whole patient, replayed through the live endpoints

```bash
.venv/bin/python scripts/live_trajectory_demo.py --from 96 --to 126 --compact
```

`P0014` from the held-out research split — a `SUDDEN_DETERIORATION` trajectory
whose ground-truth change point is window 103 — replayed unmodified at the
5-minute cadence the model was trained on, one `POST /monitoring/observations`
and one `POST /monitoring/patients/{id}/cycle` per window:

```
 win   time      HR   SpO2     RR      ΔHR   ΔSpO2     ΔRR       score    pred  risk
 102  06:30    82.6   94.6   17.4     +1.9    +0.2    +3.3   -0.075542  NORMAL  GREEN
 103 *06:35    99.3   90.4   22.5    +16.7    -4.2    +5.1   +0.212998 ANOMALY  RED
 104  06:40   101.5   89.8   22.3     +2.2    -0.6    -0.2   +0.071445 ANOMALY  RED

effective risk path   UNKNOWN×1 -> GREEN×6 -> RED×24
before change point     6 windows,   0% flagged      after   24 windows, 100% flagged
```

The model flags at exactly the ground-truth change point, with zero detection
delay, and the protocol layer escalates and holds the next dose off the back of
it. Nothing in that sequence is hard-coded — the tests assert the shape, the
model supplies the numbers.

### Parity with the research pipeline

Features and scores are checked window-by-window against the pipeline that
trained the model — 56 sampled windows across all seven scenarios, plus all 143
scoreable windows of the replayed trajectory in sequence. Both agree **bit for
bit**, with zero label disagreements (`tests/test_research_parity.py`,
`tests/test_live_trajectory_e2e.py`).

Full detail, including the temporal-state design and the first-window rule:
[`docs/LIVE_INFERENCE.md`](docs/LIVE_INFERENCE.md).

## What the demo shows

Six seeded patients, one per trajectory, all reproducible from a fixed seed:

| Patient | Trajectory | Risk progression | Next dose |
| --- | --- | --- | --- |
| P-2001 | stable | GREEN throughout | PROCEED |
| P-2002 | improving | AMBER → GREEN | PROCEED |
| P-2003 | gradual deterioration | **GREEN → AMBER → RED** | HOLD |
| P-2004 | sudden deterioration | GREEN → AMBER → RED | HOLD |
| P-2005 | recovery | **RED → AMBER → GREEN** | PROCEED |
| P-2006 | failing sensor | GREEN → **UNKNOWN** (gated) | REVIEW_REQUIRED |

P-2006 is the one to watch: the risk model still says GREEN, and the system
refuses to act on it because the SpO2 probe stopped reporting.

> **All Phase 2 thresholds are synthetic.** Every number in
> `monitoring/protocol.py` is invented for demonstration. It is not clinical
> guidance. `GET /monitoring/protocol` returns them with that warning attached.

---

## What the demo shows

`demo_screening.pdf` is deliberately not a clean pass. In one screen it
exercises every path that matters:

| Criterion | Verdict | Why it is interesting |
| --- | --- | --- |
| INC-01 Age 18–65 | PASS | Range bar, value well inside |
| INC-02 Type 2 Diabetes | PASS | Presence match |
| INC-03 HbA1c 7–10 % | PASS | Record reports HbA1c **twice** with different values → contradiction flagged, latest used |
| INC-04 eGFR ≥ 45 | PASS | Observed 47 — **borderline**, visibly hugging the threshold |
| INC-05 Metformin | PASS | Medication presence |
| EXC-01 Severe cardiovascular disease | PASS | **Rule/AI disagreement** — see below |
| EXC-02 Prior GLP-1 exposure | UNKNOWN | Outside the Phase 1 rule vocabulary; never guessed |

**Overall: REVIEW_REQUIRED · rule coverage 86%**

### The disagreement

The rule engine matches condition names literally, so "severe cardiovascular
disease" does not match the recorded "Stable Angina" and the exclusion passes.
The mock AI expands terminology through a concept table and concludes the
opposite.

That is a genuine difference in capability, not a scripted stunt. The system
reports both and stops:

```
RULE / AI DISAGREEMENT
Rule engine : PASS
AI layer    : NOT_SUPPORTED
The rule verdict stands; this screening is held for human review.
```

### Rule coverage

`rule_coverage` reports the fraction of criteria the deterministic engine could
actually express as a rule — 6 of 7 here. It is an honest statement of how much
of a screening was verified, rather than a claim that the system "understood"
the protocol.

---

## Architecture in one picture

```
Structured PDF ──► extraction ──►┌──────────────────────┐
                                 │  CANONICAL SCHEMA    │◄── POST /screen
POST /screen/pdf (adapter) ─────►│  Patient + Trial     │
                                 └──────────┬───────────┘
                                            ▼
                             Deterministic rules   ← AUTHORITATIVE
                                            ▼
                             Heuristics            ← advisory
                                            ▼
                             Mock AI / SLM         ← advisory
                                            ▼
                             Disagreement detector ← surfaces, never resolves
                                            ▼
                             ScreeningResult ──► Repository ──► data/store.json
```

`/screen/pdf` is only an adapter: it parses bytes into canonical models and
calls the same service `/screen` calls. Future OCR and LLM extraction become
additional adapters feeding the same schema.

Full detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Upgrade path through Phase 6: [`docs/PHASES.md`](docs/PHASES.md).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness plus active AI provider and repository |
| POST | `/screen` | Screen canonical `{patient, trial}` JSON — the real endpoint |
| POST | `/screen/pdf` | Adapter: multipart PDF → canonical → same service |
| GET | `/results` | All stored screening results, newest first |
| GET | `/results/{id}` | One stored result |

Phase 2, all under `/monitoring`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/protocol` | The demo protocol's thresholds, labelled synthetic |
| POST | `/treatments` | Register a screened patient onto a drug |
| POST | `/treatments/{id}/doses` | Record an administered dose |
| GET | `/treatments` | Filter by trial and/or patient |
| POST | `/observations` | Batch ingest; invalid rows refused **and reported** |
| POST | `/adverse-events` | Record a clinician-reported adverse event |
| GET | `/patients/{id}/state` | The derived projection, computed on read |
| POST | `/patients/{id}/cycle` | Run one monitoring cycle |
| GET | `/patients/{id}/cycle` | The latest cycle |
| GET | `/patients/{id}/timeline` | Append-only event log |
| GET | `/trials/{id}/overview` | Dashboard aggregate |
| POST | `/demo/seed` | Populate the synthetic cohort |

Every failure returns `{"error": {"code", "message", "details"}}`. No stack
traces escape.

## Design rules that keep it honest

- **Never invent a rule.** Unparseable criterion → `rule = None` → `UNKNOWN`.
- **Never convert units silently.** `%` vs `mmol/mol` → `UNKNOWN` + warning.
- **Never read an empty list as an absence.** No recorded medications means
  "not documented", not "not taking it".
- **`PASS` always means "satisfies this criterion for enrollment"** — inclusion
  and exclusion alike. The inversion lives in one table with dedicated tests.
- **`FAIL` dominates `UNKNOWN`.** A definite failure is not softened by missing
  data elsewhere.

## Layout

```
backend/
  app/
    schema/        canonical models — the central boundary (Phase 1 + 2)
    engine/        deterministic eligibility rules (authoritative)
    heuristics/    advisory data-quality flags
    ai/            AIProvider, MockAIProvider, disagreement detector
    extraction/    pdfplumber reader + deterministic parser
    monitoring/    Phase 2: protocol, state, gate, interventions, next dose
    risk/          RiskProvider + MockRiskProvider (the ML seam)
    synthetic/     seeded trajectory generator
    repository/    Repository + MonitoringRepository (sibling interfaces)
    api/           FastAPI routes, Phase 1 and Phase 2
    service.py     Phase 1 orchestration
  fixtures/        canonical JSON + generated demo PDFs
  scripts/         generate_demo_pdf.py, smoke_test.py
  tests/           310 tests
frontend/
  src/
    types/         TypeScript mirror of the canonical schema
    components/            CriterionLedger, RangeBar, AIPanel, ...
    components/monitoring/ TrialOverview, PatientMonitor, PatientTimeline
docs/
```

## Not built yet

Real ML/DL models, real LLM/RAG, OCR, unstructured document understanding,
Supabase, cloud sync, event streaming, authentication, and real notification
delivery (email/SMS/push). Every one has a defined seam — `RiskProvider`,
`Repository`, `MonitoringRepository`, `NotificationDeliveryProvider` — and a
place in [`docs/PHASES.md`](docs/PHASES.md).

Notification *generation* is separate from *delivery*, and nothing generates a
patient-facing message from a risk level: that stays behind human approval.
