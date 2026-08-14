# Clinical Trial Matching & Research Assistant — Phase 1

Hexaware Premier League Mavericks Hackathon · PS4

Screens a patient against a clinical trial protocol from a structured clinical
PDF, and explains every verdict it reaches.

> Deterministic rules decide eligibility. Heuristics and the AI layer are
> advisory and cannot change a verdict. Anything the engine cannot verify
> becomes `UNKNOWN` and goes to a human.

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

## Verify

```bash
cd backend
.venv/Scripts/python -m pytest tests -q     # 65 tests, no network, no PDF needed for the engine
.venv/Scripts/python scripts/smoke_test.py  # end-to-end against a running server
```

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
    schema/        canonical models — the central boundary
    engine/        deterministic rules (authoritative)
    heuristics/    advisory data-quality flags
    ai/            AIProvider, MockAIProvider, disagreement detector
    extraction/    pdfplumber reader + deterministic parser
    repository/    Repository interface + JsonRepository
    api/           FastAPI routes
    service.py     the single orchestration point
  fixtures/        canonical JSON + generated demo PDFs
  scripts/         generate_demo_pdf.py, smoke_test.py
  tests/           65 tests
frontend/
  src/
    types/         TypeScript mirror of the canonical schema
    components/    CriterionLedger, RangeBar, AIPanel, ...
docs/
```

## Not in Phase 1

OCR, unstructured document understanding, real LLM calls, RAG, vector
databases, batch screening, analytics dashboards, Supabase, cloud sync,
authentication, and patient notification. Each has a defined place in
[`docs/PHASES.md`](docs/PHASES.md); none is needed to prove the concept.
