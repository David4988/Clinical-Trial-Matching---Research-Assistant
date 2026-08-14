# Architecture — Phase 1

> Normalize first. Verify deterministically. Use AI to assist. Explain every
> result. Persist cleanly. Extend later.

## The pipeline

```
Structured clinical PDF
        │
        ▼  extraction/pdf_reader.py      pdfplumber → TextLine(page, line, text)
   text lines
        │
        ▼  extraction/parser.py          section state machine
        │  extraction/criterion_parser.py criterion text → rule | None
        ▼
╔═══════════════════════════════════════════════════════╗
║  CANONICAL SCHEMA          schema/                    ║   ← POST /screen
║  Patient + Trial (Pydantic, validated)                ║      enters here
╚═══════════════════════════════════════════════════════╝
        │
        ▼  engine/            DETERMINISTIC · AUTHORITATIVE
   CriterionResult[]          PASS / FAIL / UNKNOWN + evidence
        │
        ▼  heuristics/        ADVISORY  → HeuristicFlag[]
        │
        ▼  ai/                ADVISORY  → AIAnalysis
        │
        ▼  ai/disagreement.py           → Disagreement[]
        │
        ▼  engine/status.py   deterministic status derivation
   ScreeningResult
        │
        ▼  repository/        Repository → JsonRepository → data/store.json
```

## The canonical boundary

`app/schema/` is the contract. Everything upstream converges into it;
everything downstream consumes only it. The screening engine has no idea
whether its input came from a PDF, an LLM, OCR, a CSV, or an API call — and
that is what makes Phases 2–6 additive rather than a rewrite.

Concretely: `app/engine/` imports from `app/schema/` and nothing else.

## Two endpoints, one code path

```
POST /screen        (canonical JSON) ──┐
                                       ├──► ScreeningService.screen()
POST /screen/pdf    (adapter) ─────────┘
```

`/screen/pdf` parses bytes into `(Patient, Trial)` and then calls the same
method `/screen` calls. It contains no screening logic. Every future input
adapter joins at that same line.

This also gives the demo a fallback: if PDF extraction fails, the frontend's
"Screen the sample record instead" button posts canonical JSON to `/screen`
and the full engine still runs.

## The AI boundary

```
                Patient + Trial
                       │
                       ▼
              Deterministic rules      ← AUTHORITATIVE
                       │
                       ▼
                Heuristic layer        ← advisory
                       │
                       ▼
                Mock LLM / SLM         ← advisory
                       │
                       ▼
             Disagreement detector     ← surfaces, never resolves
                       │
                       ▼
              Status derivation        ← deterministic
```

**The AI may:** interpret criteria the rule parser could not structure,
normalise terminology, flag ambiguity, and write explanations.

**The AI may not:** set `CriterionResult.status`, set `overall_status`,
overrule a rule verdict, or be the sole basis for a PASS or FAIL.

This is enforced structurally rather than by convention. `AIProvider.analyze()`
receives the deterministic results as input and returns an `AIAnalysis` as
output; it holds no mutable reference to any `CriterionResult`. There is no
code path by which a provider — mock or real — can write an eligibility verdict.

### How disagreement arises honestly

The rule engine matches condition names literally. An exclusion for "severe
cardiovascular disease" does not match a recorded condition of "stable angina",
so the criterion passes. The mock AI expands terminology through a concept
table and reaches the opposite conclusion.

That is a real difference in capability, not a scripted stunt. The system
reports both and stops:

```
⚠ REVIEW REQUIRED
Rule engine : PASS
AI / SLM    : NOT_SUPPORTED
Neither verdict was applied. Held for human review.
```

## Criterion evaluation

`PASS` always means *"the patient satisfies this criterion for enrollment"*,
for inclusion and exclusion alike. The inversion lives in one table in
`engine/eligibility.py`:

| Rule matches | INCLUSION | EXCLUSION |
| ------------ | --------- | --------- |
| TRUE         | PASS      | **FAIL**  |
| FALSE        | FAIL      | **PASS**  |
| UNKNOWN      | UNKNOWN   | UNKNOWN   |

## Overall status derivation

Ordered, deterministic, in `engine/status.py`:

1. any `FAIL` → **INELIGIBLE** (dominates everything, including unknowns)
2. any disagreement → **REVIEW_REQUIRED**
3. any `UNKNOWN` → **REVIEW_REQUIRED**
4. any `WARN` heuristic → **REVIEW_REQUIRED**
5. otherwise → **ELIGIBLE**

## Rules that keep the engine honest

**Never invent a rule.** A criterion the parser cannot express keeps
`rule = None`, evaluates to `UNKNOWN`, and is referred to the advisory AI
layer. `rule_coverage` reports the fraction that was actually machine-evaluable
— an honest measure of how much of a screening was verified.

**Never convert units silently.** If a criterion requires `%` and the record
reports `mmol/mol`, the result is `UNKNOWN` plus a `UNIT_MISMATCH` warning.
Only pure notational variants (`%` / `percent`) are treated as equal.

**Never read an empty list as an absence.** No recorded medications means
"not documented", not "not taking it" — so a medication exclusion against an
empty list is `UNKNOWN`, not `PASS`.

**Never lose provenance.** Every `CriterionResult` carries `Evidence` with a
locator. PDF-derived facts cite `page 1, line 12`.

## Phase 1 simplifications, stated plainly

- The PDF layout is one we control. The parser is deterministic and specific,
  not general. Generality is Phase 2's job.
- Presence criteria are recognised by an explicit `Diagnosis:` / `Medication:`
  label rather than by guessing whether a word is a drug or a disease. A hidden
  drug dictionary would silently misclassify anything not in it.
- `observed_at` is a free-form string. Phase 1 does no date arithmetic.
- The mock AI's "understanding" is a hand-written concept table in
  `ai/mock_provider.py`.

## Module dependency rules

| Module         | May import                        |
| -------------- | --------------------------------- |
| `schema/`      | nothing in `app/`                 |
| `engine/`      | `schema/`                         |
| `heuristics/`  | `schema/`, `engine/`              |
| `ai/`          | `schema/`                         |
| `extraction/`  | `schema/`                         |
| `repository/`  | `schema/`                         |
| `service.py`   | all of the above                  |
| `api/`         | `service.py`, `schema/`           |

If `engine/` ever needs to import from `extraction/` or `ai/`, the boundary
has been broken.
