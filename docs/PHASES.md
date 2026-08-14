# Upgrade path

The design requirement: **Phases 2–6 extend the Phase 1 architecture rather
than rewrite the eligibility engine.**

Two interfaces make that true, and both exist in Phase 1 with a single
implementation each:

- `AIProvider` (`app/ai/provider.py`)
- `Repository` (`app/repository/base.py`)

Plus the canonical schema itself, which every input adapter must produce.

---

## Phase 1 — Structured PDF (built)

```
Structured PDF → deterministic parser → CANONICAL SCHEMA
    → rules + heuristics + mock AI → individual report → JSON repository
```

## Phase 2 — Unstructured PDF / DOCX

```
Unstructured document → LLM extractor → CANONICAL SCHEMA → same engine
```

**Changes:** add `extraction/llm_extractor.py` producing `(Patient, Trial)`.
Add a real `AIProvider` for criterion interpretation.
**Engine changes: none.** **API changes: none** — `/screen/pdf` picks an
extractor; `/screen` is untouched.

## Phase 3 — Scanned / handwritten

```
Scan → OCR → LLM extractor → CANONICAL SCHEMA → same engine
```

**Changes:** an OCR pre-stage in front of the Phase 2 extractor.
`pdf_reader.read_lines()` already isolates "bytes → addressable text", so OCR
slots in as an alternative producer of `TextLine`.
**Engine changes: none.**

## Phase 4 — Batch screening and collective analytics

```
Many patients → batch screening → aggregate → dashboard
```

**Changes:** `POST /screen/batch` loops the existing `ScreeningService.screen()`.
Analytics aggregate over stored `ScreeningResult`s — the data is already
persisted and already structured.
**Engine changes: none.**

Worth surfacing here: `rule_coverage` aggregated across a cohort is a genuinely
useful research metric — how much of a protocol is machine-checkable at all.

## Phase 5 — Supabase and cloud sync

```
JsonRepository → SupabaseRepository → cloud sync
```

**Changes:** implement `Repository` against Supabase. Add a `sync_status` field
to `ScreeningResult` and a sync queue.
**Engine changes: none.** The service depends on the interface, never on JSON.

```
Local result → sync queue → cloud database → central researcher dashboard
```

Out of scope for Phase 1: multi-user access, conflict handling, offline
reconciliation.

## Phase 6 — Researcher-approved patient notification

```
ScreeningResult → researcher review → ApprovalRecord → NotificationService → patient
```

**The rule that must survive implementation: "eligible" must never
automatically trigger a notification.**

Enforce it in the type system, not the UI:

```python
class ApprovalRecord(BaseModel):
    result_id: str
    approved_by: str          # authenticated researcher
    approved_at: datetime
    channel: Literal["EMAIL", "SMS", "APP"]

class NotificationService:
    def notify(self, approval: ApprovalRecord) -> None: ...
    #             ^^^^^^^^ never accepts a ScreeningResult
```

Because `notify()` cannot accept a `ScreeningResult`, no code path exists from
"the algorithm said eligible" to "the patient was contacted" without a human
having created an `ApprovalRecord`. The same technique used for the AI boundary
in Phase 1.

Intended researcher-facing flow:

```
Patient P-1042 · Trial CT-001 · Status: ELIGIBLE
[ Review ]  [ Approve for contact ]
```

---

## What must not change

| Invariant | Why |
| --- | --- |
| Deterministic rules stay authoritative | The AI layer is assistive at every phase, including when it becomes a real model |
| `UNKNOWN` is never coerced to PASS or FAIL | Missing data is a finding, not a gap to fill |
| Disagreements are surfaced, never auto-resolved | The escalation path is the safety property |
| Every verdict carries evidence | Explainability is the product |
| Units are never silently converted | A wrong unit is a wrong clinical decision |
