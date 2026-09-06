# TrialGuard Phase 0 Architecture Contract

> **STILL AUTHORITATIVE for field-level domain detail** — §§3–10, §12, §§15–17
> and the §20 R2 amendments — with **one exception: §11 (Persistence Contract)
> is superseded** by §§9–11 of
> **[`FINAL_IMPLEMENTATION_PLAN.md`](FINAL_IMPLEMENTATION_PLAN.md)**, which
> replaces the JSON store and its in-file `keys` index with PostgreSQL and a
> partial unique index. The `ObligationRepository` method surface is unchanged.
> The final plan is the implementation-facing source of truth; where the two
> disagree, it wins.

Status: frozen pending the sign-off in §18. Written against commit `f8e0f47`,
re-verified against the live repository during this pass. Supersedes the
schema and enum sketches in [`OBLIGATIONS_PLAN.md`](OBLIGATIONS_PLAN.md) — that
document's roadmap, ownership split and file-level plan still stand; this
document is the authoritative field-by-field contract for Phase 1 onward.

**No implementation in this document.** Every schema below is a contract, not
code — types are written in the syntax the developers will use, but nothing
here is imported by the application.

---

## 1. Purpose

Two developers are about to work in parallel. The single largest risk to that
is not a wrong design — it is two *different*, individually reasonable
designs that cannot be merged: an enum with the same name and different
values, a field that means one thing in the backend and another in the
frontend, a state machine each of them implemented from memory instead of from
a written table. This document exists to make that impossible by removing
every decision that would otherwise be made twice.

Everything in here is intended to be frozen in one commit, by both
developers, before either writes a line of Phase 1 code.

---

## 2. Existing Repository Constraints

Re-verified directly against the code in this pass, not carried over from
memory:

- **Persistence is JSON, not a database.** Two ABCs —
  [`repository/base.py`](../backend/app/repository/base.py) (5 methods,
  screening) and [`repository/monitoring_base.py`](../backend/app/repository/monitoring_base.py)
  (treatments/observations/AEs/cycles/timeline/notifications) — each backed by
  an atomic-write JSON file
  ([`json_repo.py`](../backend/app/repository/json_repo.py),
  [`json_monitoring.py`](../backend/app/repository/json_monitoring.py)). No
  ORM, no migration tool. The obligation layer gets a **third** ABC, sibling
  to both, never an extension of either.
- **IDs are opaque and non-deterministic.** [`monitoring/ids.py`](../backend/app/monitoring/ids.py)
  is `f"{prefix}-{uuid4().hex[:10]}"`. Fine as a surrogate key; **useless for
  identity** — an obligation's identity must come from a natural key, not an
  id.
- **Errors are a two-tier convention.** A domain layer raises a typed
  exception carrying `code`, `message`, `details` — `MonitoringError`
  ([`monitoring/errors.py`](../backend/app/monitoring/errors.py)) for Phase 2,
  `ReviewError(ValueError)` in [`service.py`](../backend/app/service.py) for
  Phase 1. The API layer catches it and maps `code` to an HTTP status via a
  local dict (`_STATUS_BY_CODE` in
  [`api/monitoring_routes.py`](../backend/app/api/monitoring_routes.py)),
  defaulting to `422`. The app-level handlers in
  [`main.py`](../backend/app/main.py) turn all of that into
  `{"error": {code, message, details}}`. The obligation layer adds one more
  typed exception (`ObligationError`) and one more status map, following this
  pattern exactly.
- **Requests exist only where the client holds less than the model does** —
  the docstring at the top of
  [`api/monitoring_models.py`](../backend/app/api/monitoring_models.py) states
  this outright, and every request model there proves it: the server assigns
  ids, and `now: datetime | None = None` is the only concession to
  demo-replayability. Responses are bare canonical models, not
  API-specific view models. The obligation API follows this without
  exception.
- **`Evidence` is frozen and reused, not re-invented.**
  [`schema/clinical.py`](../backend/app/schema/clinical.py) — `source_type`,
  `locator`, `snippet`, `note`, all optional except `source_type`. Every new
  evidence-bearing model uses this type verbatim.
- **`CriterionResult`** (`schema/result.py`) carries `criterion_id`, `kind`,
  `text`, `status`, `raw_match: bool | None`, `expected`, `observed: str |
  None`, `evidence: list[Evidence]`. This is the exact object the missing-lab
  detector reads.
- **`Criterion.rule`** (`schema/trial.py`) is `NumericRule | PresenceRule |
  None`, discriminated on `type`. Only `NumericRule` has a `field: str`, and
  only fields spelled `"lab:<name>"` (via `LAB_PREFIX = "lab:"`) address a
  lab value. This is the exact, and only, signal the detector keys off.
- **Enums are an explicit compatibility surface.** Both
  [`schema/enums.py`](../backend/app/schema/enums.py) and
  [`schema/monitoring_enums.py`](../backend/app/schema/monitoring_enums.py)
  state in their own docstrings that these values appear in API responses and
  frontend types, and that changing a *value* is breaking while *adding* a
  member is not. The obligation layer's enums must obey the same rule from
  day one.

None of the above is redesigned. Everything below is additive.

---

## 3. Domain Model

New file: `backend/app/schema/obligations.py`. Imports only from `schema/` —
matching the dependency table in [`ARCHITECTURE.md`](ARCHITECTURE.md), which
this contract extends (§14).

### 3.A `Obligation`

```python
class Obligation(BaseModel):
    obligation_id: str
    obligation_key: str

    trial_id: str
    patient_id: str
    type: ObligationType
    status: ObligationStatus
    priority: ObligationPriority

    requirement_ref: str
    requirement_text: str
    protocol_id: str
    source_ref: str

    title: str
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)

    first_detected_at: datetime
    last_confirmed_at: datetime
    due_at: datetime | None = None

    responsible_party_id: str | None = None
    escalation_count: int = 0
    action_count: int = 0
    last_action_at: datetime | None = None

    resolved_at: datetime | None = None
    resolution: ObligationResolution | None = None
```

Field-by-field:

| Field | Owner | Deterministic? | Changes after creation? | Part of identity? | Persisted? |
|---|---|---|---|---|---|
| `obligation_id` | `obligations/service.py`, via `ids.new_id()` | no (random) | never | **no** | yes |
| `obligation_key` | `obligations/rules.py::obligation_key()` | **yes** | never | **yes — this is identity** | yes |
| `trial_id`, `patient_id` | detector | yes | never | yes (key components) | yes |
| `type` | detector | yes | never | yes (key component) | yes |
| `status` | `reconcile.py` / `proposals.py` / `execution.py` / human dismiss | yes, per §5 table | yes — this is the lifecycle | no | yes |
| `priority` | `rules.py::priority_for()`, **recomputed on every touch** | yes | yes, as inputs change | no | yes |
| `requirement_ref` | detector | yes | never | yes (key component) | yes |
| `requirement_text` | detector, copied verbatim from the criterion / protocol table | yes | only via `REQUIREMENT_CHANGED` (§9) | no | yes |
| `protocol_id` | detector (`protocol.PROTOCOL_ID` or `trial_id` for Phase 1 rules) | yes | no | no | yes |
| `source_ref` | detector — the `result_id` or `cycle_id` that first raised it | yes | **no — first-raise only**, not updated on touch | no | yes |
| `title`, `detail` | **deterministic template**, never the LLM | yes | yes, regenerated on touch from current fields | no | yes |
| `evidence` | detector, from `CriterionResult.evidence` + the criterion itself | yes | replaced wholesale on touch (current evidence, not accumulated) | no | yes |
| `first_detected_at` | `reconcile.py`, set once | yes (`now` at create time) | **never — this is the point of the field** | no | yes |
| `last_confirmed_at` | `reconcile.py`, bumped on every touch | yes | yes, every reconciliation pass | no | yes |
| `due_at` | detector, if the requirement has a temporal bound; `None` for a standing lab requirement | yes | rarely | no | yes |
| `responsible_party_id` | `parties.py::resolve()` — **never the LLM** | yes | recomputed on touch, may be `None` | no | yes |
| `escalation_count` | `execution.py`, incremented when a proposal executes while status is already `AWAITING_RESPONSE` | yes | monotonic increase | no | yes |
| `action_count` | `service.py`, incremented on every `ObligationAction` append | yes | monotonic increase | no | yes |
| `last_action_at` | `service.py`, set to the `occurred_at` of the latest `ObligationAction` | yes | yes, on every action | no | yes |
| `resolved_at`, `resolution` | `reconcile.py` (auto) or the dismiss endpoint (human) | yes (auto) / n/a (human) | set once, obligation is terminal after | no | yes |

`ObligationResolution` — a frozen sub-record, not a bare enum, for the same
reason `EligibilityOverride` in
[`schema/monitoring.py`](../backend/app/schema/monitoring.py) is a record and
not a boolean: "who decided this, and why" must never be omissible.

```python
class ObligationResolution(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: ResolutionKind          # SATISFIED | DISMISSED | SUPERSEDED
    by: str                       # "SYSTEM" or a reviewer's name
    note: str                     # required even for SATISFIED — "why", e.g.
                                   # "detector no longer reports INC-04 as UNKNOWN"
    at: datetime
```

**Deliberately not a field on `Obligation`:** a `notes` or `assignee` field.
Nothing in the current brief needs either, and both are the kind of field
that grows scope silently. If a developer finds they need one mid-build, that
is a signal to come back to this document rather than add it ad hoc.

### 3.B `ObligationAction` — the follow-up ledger

```python
class ObligationAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    obligation_id: str
    seq: int
    kind: ObligationActionKind
    occurred_at: datetime
    actor_kind: ActorKind
    actor_name: str | None = None
    channel: NotificationChannel | None = None
    recipient_party_id: str | None = None
    ref_id: str | None = None
    note: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
```

- **Frozen and append-only** — the same discipline as `MonitoringEvent`. No
  method in the repository interface may update or delete a row in the
  `actions` collection; only `append_actions(list[ObligationAction])` exists.
- **`seq` is required, not optional**, and is assigned by
  `obligations/service.py` as `(max existing seq for this obligation_id) + 1`
  at append time — never by the caller, never by a wall-clock comparison.
  This is what makes "escalation #2" a lookup rather than a computation
  scattered across the codebase.
- **`actor_name` is required when `actor_kind is ActorKind.RESEARCHER`** and
  must be `None` otherwise — enforced in `service.py`, mirroring
  `InvestigatorReviewService.record()`'s `REVIEWER_REQUIRED` check.
- **Valid `ObligationActionKind` values** (§4) are a closed set. There is no
  freeform action kind — a new kind of ledger entry means adding an enum
  member, in the shared Phase 0 commit, not a string literal chosen at a call
  site.
- **Do these duplicate the timeline?** No — see §12. Only a named subset of
  kinds also produces a `MonitoringEvent`; most do not.

### 3.C `ProposedAction`

Validated against the repository: it must be a separate persisted entity, not
a field on `Obligation` or a transient response, for two structural reasons —
its lifecycle (`DRAFT → APPROVED/REJECTED → EXECUTED/FAILED`) is independent
of the obligation's own lifecycle (§5 vs §6), and `obligation_ids` must be a
list from the start so batching (multiple obligations, one communication,
e.g. two missing labs for the same patient sent as one email) never forces a
schema migration later.

```python
class ProposedAction(BaseModel):
    proposal_id: str
    obligation_ids: list[str]
    trial_id: str
    patient_ids: list[str]

    action_type: ProposedActionType
    status: ProposalStatus

    recipient_party_id: str
    channel: NotificationChannel

    subject: str
    body: str
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)

    provenance: ProposalProvenance
    created_at: datetime
    decision: ProposalDecision | None = None
    execution: ProposalExecution | None = None
```

```python
class ProposalProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)
    generated_by: str                  # "agent:<model>@<prompt_v>" |
                                        # "deterministic-template"
    model_name: str | None = None
    prompt_version: str | None = None
    tools_called: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    degraded: bool = False
    unresolved: list[str] = Field(default_factory=list)

class ProposalDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: Literal["APPROVED", "REJECTED"]
    reviewer: str
    note: str
    decided_at: datetime
    edited_subject: str | None = None
    edited_body: str | None = None

class ProposalExecution(BaseModel):
    model_config = ConfigDict(frozen=True)
    executed_at: datetime
    provider: str
    notification_id: str | None = None
    error: str | None = None
```

`ProposalProvenance` and `ProposalDecision` and `ProposalExecution` are each
**frozen** — once a proposal moves past `DRAFT`, the record of what was
generated, what was decided, and what happened are historical facts and are
never edited in place. `ProposedAction.decision` / `.execution` transition
from `None` to a value exactly once each; there is no code path that replaces
a set value.

`edited_subject` / `edited_body` sit **beside** `subject` / `body`, never
overwriting them — identical to how `ScreeningReview` sits beside
`ScreeningResult` rather than mutating its verdict. This is what lets the
system answer "what did the model write, and what did the human change?"

### 3.D `ApprovalRecord`

```python
class ApprovalRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    proposal_id: str
    approved_by: str
    approved_at: datetime
    channel: NotificationChannel
    subject: str
    body: str
```

**The critical invariant, stated as a type-system fact, not a runtime
check:**

```python
class ExecutionService:
    def execute(self, approval: ApprovalRecord) -> ProposalExecution: ...
    #                  ^^^^^^^^^^^^^^^^^^^^^^^ no other type is accepted.
    #             There is no execute(obligation) and no execute(proposal).
```

`ApprovalRecord` is constructible in exactly one place —
`ObligationProposalService.approve()` — and only after `reviewer` and `note`
are both non-empty (mirroring `InvestigatorReviewService.record`'s
`REVIEWER_REQUIRED` / `REVIEW_NOTE_REQUIRED`). Its `subject`/`body` are the
**final, post-edit** text — `edited_subject or subject`, `edited_body or
body` — so `execute()` never has to know whether an edit happened; it just
sends what is in front of it. This is the literal implementation of the rule
already written in [`docs/PHASES.md`](PHASES.md) §"Phase 6":

> Because `notify()` cannot accept a `ScreeningResult`, no code path exists
> from "the algorithm said eligible" to "the patient was contacted" without a
> human having created an `ApprovalRecord`.

### 3.E `ResponsibleParty`

The one piece of domain the repository has no precedent for at all — there is
no `Site`, no `Investigator`, no contact record anywhere in
`backend/app/schema/`. Kept minimal on purpose: this is a lookup table, not a
CRM.

```python
class ResponsibleParty(BaseModel):
    model_config = ConfigDict(frozen=True)
    party_id: str
    display_name: str
    role: PartyRole
    site_id: str | None = None
    email: str | None = None
    phone: str | None = None
    trial_ids: list[str] = Field(default_factory=list)
```

Loaded from a new `backend/fixtures/parties.json` through a new
`fixtures_loader.load_parties()`, exactly as `load_trial` / `load_patient`
already work. **The LLM never constructs or selects a `ResponsibleParty`.**
`parties.py::resolve(obligation) -> ResponsibleParty | None` is a pure
function over `Obligation.type`, `.trial_id`, and `TreatmentAssignment.site_id`
(new optional field, §14). If it cannot resolve, it returns `None` and the
obligation's `responsible_party_id` stays `None` — this is a valid, expected
state (§18), not an error.

---

## 4. Enum Definitions

### Placement rule

Two files, decided by one question: **does an existing consumer need this
value, or is it new vocabulary?**

- **`backend/app/schema/monitoring_enums.py`** — extend only with the six
  `MonitoringEventType` members in §12. Nothing else. This file is a
  known merge-conflict hotspot the moment two developers touch it in the
  same week, and its own docstring already documents "adding a member is not
  breaking" — so the extension is safe, but it must be the *only* Phase 0
  change to this file, made once, in the joint commit.
- **`backend/app/schema/obligation_enums.py`** *(new file)* — every enum that
  is genuinely new vocabulary. All of the following live here:

| Enum | Members | Notes |
|---|---|---|
| `ObligationType` | `MISSING_LAB_EVIDENCE`, `MISSING_REQUIRED_OBSERVATION` | **Two, not six.** `DATA_DISCREPANCY`, `LATE_VISIT`, `PROTOCOL_DEVIATION`, `INCOMPLETE_EVIDENCE` are real future types but have no detector, no fixture data, and no test in this phase — adding them now is exactly the "don't add every possible type" trap the brief warns against. Add a type when its detector ships (§16 has the pattern), not before. |
| `ObligationStatus` | `OPEN`, `AWAITING_RESPONSE`, `RESOLVED`, `DISMISSED` | Four, per §5. No `PENDING_APPROVAL` or `SENT` — those are proposal states (§6). |
| `ObligationPriority` | `LOW`, `MEDIUM`, `HIGH`, `URGENT` | Four levels, matching the coarseness of `RiskLevel`/`Severity` elsewhere in the codebase rather than inventing a numeric score. |
| `ObligationActionKind` | `DETECTED`, `RECONFIRMED`, `PARTY_RESOLVED`, `INVESTIGATED`, `PROPOSAL_CREATED`, `PROPOSAL_APPROVED`, `PROPOSAL_REJECTED`, `MESSAGE_SENT`, `DELIVERY_FAILED`, `RESPONSE_RECEIVED`, `ESCALATED`, `RESOLVED`, `DISMISSED`, `REQUIREMENT_CHANGED` | 14 members (`REQUIREMENT_CHANGED` added per the resolved decision in §9). |
| `ActorKind` | `SYSTEM`, `AGENT`, `RESEARCHER` | Deliberately distinct from `InvestigatorAction` (`monitoring_enums.py`) — that enum answers "what did a human decide clinically", this one answers "what kind of actor performed a ledger action". Conflating them would let a ledger entry look like a clinical decision. |
| `ProposalStatus` | `DRAFT`, `APPROVED`, `REJECTED`, `EXECUTED`, `FAILED` | Five. See §6 for why this is not `ObligationStatus`. |
| `ProposedActionType` | `REQUEST_LAB_EVIDENCE`, `REQUEST_REPEAT_OBSERVATION`, `ESCALATE_TO_INVESTIGATOR` | Matches the two `ObligationType`s plus one manual escalation path a researcher can trigger regardless of type. |
| `PartyRole` | `SITE_COORDINATOR`, `INVESTIGATOR`, `LAB`, `CLINICIAN` | Matches who `parties.resolve()` can name for the two obligation types in scope. |
| `ResolutionKind` | `SATISFIED`, `DISMISSED`, `SUPERSEDED` | `SUPERSEDED` is unused by any detector in this phase but is cheap to include now and expensive to retrofit into `ObligationResolution.kind` later, since that field is used in persisted, frozen records. |

**Not a new enum:** `NotificationChannel`. It already exists in
`monitoring_enums.py` (`IN_APP`, `EMAIL`, `SMS`, `PUSH`) and is reused as-is —
`ProposedAction.channel` and `ObligationAction.channel` both take this exact
type. Do not create a second channel enum.

**Merge-conflict minimization, explicit:** every enum above is a **new
file**. Two developers adding members to a shared file in the same week is
the single highest-probability conflict in this build; a new file has none.
The only edit to a pre-existing enum file in all of Phase 0 is the six-member
addition to `MonitoringEventType`, and it happens once, in the joint commit,
never again.

---

## 5. Obligation State Machine

The brief's sketch is validated with one structural correction carried over
from the previous planning pass and restated precisely here because it is
the single most consequential design decision in this contract: **the
sketch's `PENDING_APPROVAL → APPROVED → SENT` chain is proposal state, not
obligation state.** An obligation can have two proposals in flight to two
different parties; it cannot be in two states at once. Mixing them was the
brief's one real ambiguity, and separating them is what makes this contract
unambiguous.

```
        detector fires
              │
              ▼
          ┌───────┐   a proposal reaches EXECUTED   ┌────────────────────┐
          │ OPEN  │ ───────────────────────────────►│ AWAITING_RESPONSE  │
          └───┬───┘                                 └─────────┬──────────┘
              │                                               │
              │ detector no longer reports it       ┌─────────┘ detector no longer
              │ ──────────┐                          │ reports it, or researcher closes
              │           ▼                          ▼
              │      ┌──────────────────────────────────┐
              │      │            RESOLVED               │  terminal
              │      └──────────────────────────────────┘
              │
              │ researcher dismisses (reviewer + note required)
              ▼
          ┌───────────┐
          │ DISMISSED │  terminal
          └───────────┘
```

### Transition table

| From | To | Trigger | Actor | Automatic? | Preconditions |
|---|---|---|---|---|---|
| — | `OPEN` | detector reports a requirement whose key has no non-terminal obligation | System | yes | none |
| `OPEN` | `OPEN` (touch) | detector reports the same key again | System | yes | none — `first_detected_at` unchanged, `last_confirmed_at` bumped |
| `OPEN` | `AWAITING_RESPONSE` | a `ProposedAction` for this obligation reaches `EXECUTED` | System | yes, but only reachable after a human `approve()` | a proposal exists referencing this `obligation_id` and has an `ApprovalRecord` |
| `OPEN` | `RESOLVED` | detector stops reporting the key, within a **completed** detection scope | System | yes | `DetectionScope` for this `(trial_id, patient_id, source)` ran to completion (§9) |
| `OPEN` | `DISMISSED` | researcher-initiated | **Human only** | no | `reviewer` and `note` both non-empty |
| `AWAITING_RESPONSE` | `AWAITING_RESPONSE` (re-touch) | a *further* proposal for this obligation reaches `EXECUTED` | System | yes, after a human `approve()` | `escalation_count += 1` |
| `AWAITING_RESPONSE` | `RESOLVED` | detector stops reporting the key, in scope; **or** researcher explicitly closes | System / **Human** | yes / no | scope complete, or reviewer + note |
| `AWAITING_RESPONSE` | `DISMISSED` | researcher-initiated | **Human only** | no | reviewer + note |
| `RESOLVED` | anything | **forbidden** | — | — | terminal |
| `DISMISSED` | anything | **forbidden** | — | — | terminal |

**Answers to the brief's explicit questions:**

- **Can an obligation reopen?** No. A key re-detected after `RESOLVED` or
  `DISMISSED` creates a **new** `Obligation` row (new `obligation_id`, same
  `obligation_key` only if the `occurrence` component differs — see §9;
  otherwise this is an error condition the reconciler must never produce,
  because it would mean the key index is out of sync with the terminal
  status filter). Reopening the same row would corrupt `first_detected_at`
  and make the escalation count meaningless.
- **Can a resolved obligation ever change?** No field on a terminal
  obligation changes, ever, including `evidence` or `priority`. This is
  enforced by `service.py` refusing any mutation call — `touch()`,
  `attach_action()`, `resolve()`, `dismiss()` — against a non-`OPEN`/
  `AWAITING_RESPONSE` obligation, raising `ObligationError("OBLIGATION_TERMINAL", ...)`.
- **What happens if the detector fires again on an `OPEN` obligation?** A
  touch: `last_confirmed_at` advances, `title`/`detail`/`evidence`/`priority`
  are recomputed from the newly detected `DetectedRequirement`, and — unless
  the throttle in §10 suppresses it — a `RECONFIRMED` ledger entry is
  appended. `first_detected_at` and `status` are untouched.
- **What happens if the researcher dismisses it?** Terminal immediately,
  `resolution.kind = DISMISSED`, `resolution.by = <reviewer>`. Any `DRAFT`
  proposal referencing it is *not* auto-rejected by this action — dismissal
  and proposal rejection are independent facts, and a dangling `DRAFT` on a
  dismissed obligation is caught by validation the next time anyone tries to
  approve it (`OBLIGATION_TERMINAL`, §18), not by a cascading side effect.
- **What happens after escalation?** Nothing changes about the obligation's
  *status* — it is already `AWAITING_RESPONSE` and stays there.
  `escalation_count` increments and a new `ObligationAction` with
  `seq = n+1` records it. This is why escalation is answered next.
- **Is escalation a state or a property?** **A property** —
  `Obligation.escalation_count: int`, driven by counting `MESSAGE_SENT`
  entries in the ledger for this obligation. Making it a state would force a
  false choice between "escalated" and "awaiting response", which are
  simultaneously true.
- **Can multiple proposals exist for one obligation?** Yes, sequentially:
  at most **one undecided** (`status is DRAFT`) proposal per obligation at
  any time (enforced in `propose()`, §6), but any number of resolved
  (`APPROVED`/`REJECTED`/`EXECUTED`/`FAILED`) proposals accumulate in its
  history. `obligation_ids: list[str]` on `ProposedAction` additionally
  allows one proposal to span multiple obligations (batching).
- **Can multiple communications exist?** Yes — every `EXECUTED` proposal
  produces one `Notification` and one `MESSAGE_SENT` ledger entry;
  `escalation_count` is exactly the count of these beyond the first.
- **What does "awaiting response" actually mean, precisely?** *"At least one
  proposal for this obligation has been approved and sent, and the
  requirement it concerns has not yet been satisfied or closed."* It does
  **not** mean "we are certain a human will reply" — the state is entered on
  send, not on receipt, and is left only by the requirement resolving or by
  a human decision. A reply that merely says "will do" (§17, step 14) does
  not change this state; only new evidence satisfying the underlying
  requirement, or a human closing it, does.

---

## 6. Proposal State Machine

**Deliberately a separate enum and a separate field, on a separate entity.**
Why this must not be merged into `ObligationStatus`, stated plainly: an
obligation is "a requirement is not currently met." A proposal is "here is a
specific piece of outbound work, at a specific point in its own approval
pipeline." One obligation can spawn a `REJECTED` proposal, then a second
`DRAFT`, then an `EXECUTED` one — three proposal-state transitions during
which the obligation itself only ever does one thing: move from `OPEN` to
`AWAITING_RESPONSE` once, when the *first* proposal executes. Collapsing
these would mean either the obligation regresses state on every rejected
draft (nonsensical — the requirement gap hasn't changed) or the proposal
loses its own history (the exact "did we already ask, and did it get
rejected twice" question the ledger exists to answer).

```
        propose()
           │
           ▼
       ┌────────┐  approve()  ┌──────────┐  execute() succeeds  ┌──────────┐
       │ DRAFT  │────────────►│ APPROVED │──────────────────────►│ EXECUTED │  terminal
       └───┬────┘             └────┬─────┘                       └──────────┘
           │                       │
           │ reject()              │ execute() raises
           ▼                       ▼
       ┌──────────┐           ┌────────┐
       │ REJECTED │  terminal │ FAILED │  terminal, but retriable via a NEW proposal
       └──────────┘           └────────┘
```

| From | To | Trigger | Actor | Precondition |
|---|---|---|---|---|
| — | `DRAFT` | `propose()` (agent-produced or template fallback) | System / Agent | obligation is `OPEN` or `AWAITING_RESPONSE`; no existing undecided proposal for this obligation |
| `DRAFT` | `APPROVED` | `approve(reviewer, note, ...)` | **Human only** | `reviewer` and `note` non-empty |
| `DRAFT` | `REJECTED` | `reject(reviewer, note)` | **Human only** | `reviewer` and `note` non-empty |
| `APPROVED` | `EXECUTED` | `execute(approval)` succeeds | System, triggered by the approval call | provider `deliver_with_outcome` reports success |
| `APPROVED` | `FAILED` | `execute(approval)` raises or the provider reports failure | System | — |
| `EXECUTED` / `REJECTED` / `FAILED` | anything | **forbidden** | — | terminal |

A `FAILED` proposal is not retried automatically (§11, §18) — a fresh
`propose()` call creates an independent `DRAFT`, and the failed one remains
in history exactly as it failed.

---

## 7. Identity / Deduplication Contract

### The natural key

```python
def obligation_key(
    trial_id: str,
    patient_id: str,
    type: ObligationType,
    requirement_ref: str,
    occurrence: str = "",
) -> str:
    return "|".join([trial_id, patient_id, type.value, requirement_ref, occurrence])
```

Worked example, this phase's actual data:

```
CT-001|P-3311|MISSING_LAB_EVIDENCE|INC-04|
```

Four detector runs at 10:00, 10:15, 10:30, 10:45 all compute this exact
string. `reconcile.py` looks it up in the `keys` index (§11); found → touch;
not found → create. **One obligation, deterministically, with no clock or
counter involved in the key itself.**

### What `occurrence` means, precisely

An obligation type can describe either a **standing** requirement (a lab that
has never arrived; a vital sign currently absent — no natural notion of
"which instance") or a **recurring** one (Week-8 panel, then Week-16 panel —
two genuinely different obligations that happen to share a requirement
type). `occurrence` is the field that distinguishes the latter case, and it
is a plain string the detector supplies — e.g. `"WEEK-8"` — not a database
sequence.

**Phase 0 decision: `occurrence` is defined in the contract but populated by
neither shipped detector.** Both `MISSING_LAB_EVIDENCE` (screening — a
criterion is either satisfied or it isn't, once) and
`MISSING_REQUIRED_OBSERVATION` (monitoring — a required vital sign is either
present or absent right now) are standing requirements. The field exists so a
future recurring-requirement detector needs no key-function change — a
one-line detector addition, not a schema migration.

### Protocol version — resolved

**Decision: protocol version is excluded from the key.** There is no
protocol versioning anywhere in this repository today —
`protocol.PROTOCOL_ID` is a bare module constant. If a future protocol
version changes what `INC-04` requires, the *obligation is updated in
place* — `requirement_text` and `evidence` are refreshed by the next touch —
and a `REQUIREMENT_CHANGED` ledger entry (added to `ObligationActionKind` in
§4 specifically for this) records the change. Including version in the key
would silently orphan the open obligation and discard its entire follow-up
history on every threshold tweak — precisely the spam the ledger exists to
prevent. This was an open decision in the prior planning pass; it is closed
here.

### Can a resolved obligation spawn another?

Yes, but only via a **different** key — meaning, in this phase, a different
`requirement_ref` or a different `type`, since `occurrence` is unpopulated.
A `RESOLVED` `MISSING_LAB_EVIDENCE|INC-04` obligation and a later-created
`MISSING_LAB_EVIDENCE|INC-07` obligation for the same patient are unrelated
rows. There is no path in this phase by which the *same* key produces a
second row while a terminal one already exists for it — see the reopen
answer in §5.

### Standing vs. recurring, restated

A standing requirement's obligation is created once and lives until the
requirement is met or dismissed — full stop. A recurring requirement (not
implemented this phase) would instead see the reconciler close out
occurrence `N` and open occurrence `N+1` as the schedule advances, each with
its own key and its own full ledger. The contract is future-proofed for this
without building it.

---

## 8. Reconciliation Contract

```python
def reconcile(
    scope: DetectionScope,
    detected: list[DetectedRequirement],
    existing: list[Obligation],
    now: datetime,
) -> ObligationDelta:
```

A **pure function** — no repository handle, no clock read, no I/O, no model
call. `obligations/service.py` is the only caller, and it is the only thing
that persists the `ObligationDelta`. This mirrors the existing discipline in
`build_patient_state` and `build_interventions`, and it is what makes dedup
testable with zero fixtures beyond plain Python objects.

### `DetectionScope` — the safety mechanism

```python
class DetectionScope(BaseModel):
    trial_id: str
    patient_id: str
    source: DetectorSource   # SCREENING | MONITORING_OBSERVATION
```

`existing` passed into `reconcile()` must be **pre-filtered** to exactly this
scope by the caller — every non-terminal obligation for this
`(trial_id, patient_id, source)` and no others. A "completed detector run"
means: the detector function returned normally (no exception propagated) and
produced its full `list[DetectedRequirement]`, however short — including
empty. **Auto-resolve is only safe because `existing` is scoped this
tightly**; if the detector raised, the caller must not call `reconcile()` at
all for that scope (§18), which means no obligation in that scope is ever
touched or resolved on a failed run. This is the direct answer to "how do we
avoid accidentally resolving everything because a detector failed" — the
failure never reaches `reconcile()` in the first place.

### `CREATE`

**When:** a `DetectedRequirement`'s computed key has no entry in the scoped
`existing` list.
**What happens:** a new `Obligation` with `status=OPEN`,
`first_detected_at = last_confirmed_at = now`, `resolved_at = None`,
`escalation_count = action_count = 0`. One `ObligationAction(seq=1,
kind=DETECTED, actor_kind=SYSTEM)` is appended in the same service call.

### `TOUCH`

**When:** a `DetectedRequirement`'s key matches an existing obligation's key.
**Fields that change:** `last_confirmed_at` (always, to `now`); `title`,
`detail`, `evidence`, `priority`, `responsible_party_id` (recomputed fresh
from the current `DetectedRequirement` and current `parties.resolve()` — not
merged with the old values, replaced).
**Fields that must never change on a touch:** `obligation_id`,
`obligation_key`, `first_detected_at`, `source_ref`, `status`,
`escalation_count`, `resolved_at`, `resolution`. A test asserting every one
of these is byte-identical before and after a touch is part of the required
suite (§19).
**Ledger:** a `RECONFIRMED` entry is appended **only if** more than
`RECONFIRM_LEDGER_INTERVAL` (default 6h) has elapsed since the last one for
this obligation — otherwise the field update happens with no ledger row.
Without this throttle, a five-minute monitoring cadence would produce one
`RECONFIRMED` row per cycle, forever, making the ledger unreadable.

### `AUTO-RESOLVE`

**When it is safe:** an obligation in the scoped `existing` list whose key
does **not** appear in `detected` — and only because `detected` is known
(by the `DetectionScope` contract above) to represent a complete run.
**What happens:** `status → RESOLVED`, `resolved_at = now`,
`resolution = ObligationResolution(kind=SATISFIED, by="SYSTEM", note=<templated
from what stopped matching>, at=now)`. One `ObligationAction(kind=RESOLVED,
actor_kind=SYSTEM)` is appended.
**When it must never fire:** if the detector raised (scope never reached
`reconcile()`), if the obligation is already terminal (not in the scoped
`existing` list by construction — terminal obligations are excluded from
what the caller passes in), or if the obligation belongs to a different
`(trial_id, patient_id, source)` than the scope names (structurally
impossible given the pre-filter, but worth a defensive assertion in
`service.py` — see §18).

---

## 9. Agent Boundary

### What the agent may do

Read context through the tool registry; retrieve evidence; synthesize a
situation summary; investigate ambiguity in what it retrieves; classify
inbound free text (§17-adjacent, Phase 13); draft subject/body text for a
proposal.

### What the agent may never do

Directly construct or mutate an `Obligation`, `ObligationAction`,
`ProposedAction`, or `ApprovalRecord`; choose a `responsible_party_id`;
transition any state; call a `NotificationDeliveryProvider`; write to any
repository. **Enforced structurally, not by convention:** `backend/app/agent/`
imports a read-only `TrialReadFacade` and nothing else from `obligations/` or
`repository/`. Add this to the dependency table in `ARCHITECTURE.md` (§14)
so it is checkable the same way the existing `engine/` → `schema/`-only rule
is checkable.

### Interface: packed evidence, with a real tool registry underneath

The repository investigation confirms the tools should be genuinely typed,
individually testable functions — not because the agent calls them in a
loop by default, but because a stub-testable registry is what makes
`agent/evidence.py`'s deterministic evidence pack constructible without a
running model, and what makes `AGENT_MODE=tools` (§13 of the prior plan; not
built this phase) a real fallback path rather than a rewrite. **Phase 0
decision: `agent/` exposes both — the tools as real functions in
`agent/tools.py`, and `agent/evidence.py` calling them in a fixed order to
assemble one pack for a single structured LLM call.** This matches the
structure proposed in the brief (`tools.py`, `evidence.py`, `investigate.py`)
and validates it against the repository: nothing here conflicts with
existing conventions, because nothing in `agent/` yet exists to conflict
with — this is genuinely new ground, constrained only by the dependency
rule above and by the type contracts in §3.

`InvestigationOutput` (unchanged from the prior plan, restated because it is
the enforcement mechanism): no field capable of holding a decision, a
recipient, a status, or a priority. `escalation_number` is emitted by the
model but **overwritten** by the ledger's actual count before the value is
used anywhere — the model's number is advisory-only and any disagreement is
recorded in `unresolved`, never trusted.

---

## 10. Read/Write Dependency Rules

| Component | Reads | Writes | Can call LLM? | Can mutate clinical state? |
|---|---|---|---|---|
| Detector (`detectors/*.py`) | `ScreeningResult` / `PatientState` + `MonitoringCycleResult` (pure function args, no repo handle) | nothing | No | No |
| Reconciler (`reconcile.py`) | `list[DetectedRequirement]`, `list[Obligation]` (both passed in) | nothing — returns a delta | No | No |
| `ObligationService` | `ObligationRepository` | `ObligationRepository` (obligations, actions), `MonitoringRepository.append_events` (milestones only, §12) | No | No — an obligation is metadata about a requirement gap, never a clinical value |
| `agent/` (tools, evidence, investigate) | `TrialReadFacade` only — a read-only view over `ObligationRepository`, `MonitoringRepository`, `Repository` (screening) | nothing | **Yes** | No |
| `ObligationProposalService` (`proposals.py`) | `ObligationRepository`, `PartyRegistry` | `ObligationRepository` (proposals, actions) | No | No |
| Approval (`proposals.py::approve`/`reject`) | `ObligationRepository` | `ObligationRepository` (proposal decision, actions) | No | No — this is where a *human* decision is recorded, structurally identical to `InvestigatorReviewService.record` |
| `ExecutionService` (`execution.py`) | `ObligationRepository` | `ObligationRepository` (execution, obligation status), `MonitoringRepository.save_notifications` | No | **External action only** — sends a message; never writes a lab value, a vital sign, or an eligibility verdict |
| Timeline (`MonitoringEvent` via existing `MonitoringRepository`) | — | append-only, milestone subset (§12) | No | Audit/history only |

The one row worth calling out explicitly: **`ObligationService` cannot call
the LLM.** Investigation is a separate, later, optional step
(`POST /obligations/{id}/investigate`) — an obligation is fully valid,
queryable, and displayable with zero agent involvement, which is exactly
what makes the work queue demoable before the agent exists (§19, and the
build-order rationale in the prior plan).

---

## 11. Persistence Contract

> **SUPERSEDED by [`FINAL_IMPLEMENTATION_PLAN.md`](FINAL_IMPLEMENTATION_PLAN.md)
> §§9–11.** Persistence is PostgreSQL (SQLAlchemy 2.x Core + psycopg 3,
> migrated with Alembic, hosted on Supabase), not JSON. The `keys` index below
> is replaced by a partial unique index on `obligation_key` over non-terminal
> rows. **Do not build `json_obligations.py` as the primary store** — it exists
> only as the `PERSISTENCE=json` rollback path. Everything else in this
> document stands. The `ObligationRepository` method surface listed below is
> unchanged, plus `transaction()`.


**No ORM, no relational database.** The repository investigation gives no
evidence that JSON-backed persistence is untenable for this feature — the
existing monitoring store already handles higher write volume (a batch
observation ingest touches the store more than an obligation lifecycle
ever will) with the same technique proposed here.

### One store, three collections

`backend/data/obligations.json` — a **third** file, sibling to
`store.json` (screening) and `monitoring.json` (monitoring), resolved
through the existing `repository/paths.py::data_dir()` with no changes to
that module.

```python
_EMPTY: dict[str, dict] = {
    "obligations": {},   # obligation_id -> Obligation (JSON)
    "keys": {},           # obligation_key -> obligation_id   (the identity index)
    "actions": {},         # obligation_id -> list[ObligationAction] (JSON), append-only
    "proposals": {},        # proposal_id -> ProposedAction (JSON)
}
```

- **New ABC:** `backend/app/repository/obligation_base.py` —
  `ObligationRepository(ABC)`, sibling to `Repository` and
  `MonitoringRepository`, never inheriting from either. Method surface:
  `save_obligation`, `get_obligation`, `get_by_key`, `list_obligations(trial_id,
  patient_id=None, status=None)`, `append_actions(list[ObligationAction])`,
  `list_actions(obligation_id)`, `save_proposal`, `get_proposal`,
  `list_proposals(obligation_id=None, status=None)`.
- **New implementation:** `backend/app/repository/json_obligations.py` — the
  exact mechanics already proven in `json_monitoring.py`: `tempfile.mkstemp`
  + `os.replace` atomic write, an in-memory cache keyed on
  `(mtime_ns, size)`, `_EMPTY` section defaults on a missing file.
- **The `keys` index exists for one reason:** reconciliation is the one
  operation that runs on every screening and every monitoring cycle, and it
  needs "does this key already have a non-terminal obligation" to be a dict
  lookup, not a full-collection scan. Every other read path (`list_obligations`,
  the queue) can afford to scan the (small, demo-scale) `obligations` dict
  directly.
- **IDs:** `ids.new_id("OB")`, `ids.new_id("OA")`, `ids.new_id("PA")` — three
  new prefixes added to `monitoring/ids.py`'s existing prefix constants,
  following the exact pattern of `TX`, `OBS`, `IV`, etc. Surrogate keys only;
  never used for identity or dedup (§7).
- **Concurrency:** single-process only, matching the existing store's
  documented constraint. Read-modify-write with no locking is exactly what
  `json_monitoring.py` already accepts; the obligation store inherits the
  same limitation and the same mitigation — `uvicorn` without `--workers`,
  documented in [`DEPLOYMENT.md`](DEPLOYMENT.md).
- **Loading:** `_load()` on a missing file returns `_EMPTY` and the first
  `_write()` creates it — no migration step, no backfill script required for
  the store to exist.

---

## 12. Timeline Contract

**No separate audit store.** Two records answer two different questions, and
the rule for which gets which is closed-form, not case-by-case judgment:

- `ObligationAction` answers *"what has happened about this specific
  requirement?"* — every ledger kind lands here, always, in `seq` order.
- `MonitoringEvent` answers *"what happened to this patient?"* — only
  **milestones**, because it is rendered top-to-bottom by
  [`PatientTimeline.tsx`](../frontend/src/components/monitoring/PatientTimeline.tsx)
  and a row per monitoring cycle's `RECONFIRMED` touch would drown every
  other kind of event on that page within hours of the demo cohort running.

| `ObligationActionKind` | Also a `MonitoringEvent`? | New `MonitoringEventType` |
|---|---|---|
| `DETECTED` | **yes** | `OBLIGATION_RAISED` |
| `RECONFIRMED` | no | — |
| `PARTY_RESOLVED` | no | — |
| `INVESTIGATED` | no | — |
| `PROPOSAL_CREATED` | **yes** | `PROPOSAL_CREATED` |
| `PROPOSAL_APPROVED` | **yes** | `PROPOSAL_DECIDED` |
| `PROPOSAL_REJECTED` | **yes** | `PROPOSAL_DECIDED` (same type, `payload.outcome` distinguishes) |
| `MESSAGE_SENT` | **yes** | `PROPOSAL_EXECUTED` |
| `DELIVERY_FAILED` | **yes** | `PROPOSAL_EXECUTED` (same type, `payload.error` distinguishes) |
| `RESPONSE_RECEIVED` | no (this phase) | — inbound is untrusted; ledger only until a human confirms it changes something |
| `ESCALATED` | no | — derivable by counting `PROPOSAL_EXECUTED` events for the same obligation |
| `RESOLVED` | **yes** | `OBLIGATION_RESOLVED` |
| `DISMISSED` | **yes** | `OBLIGATION_DISMISSED` |
| `REQUIREMENT_CHANGED` | no | — plumbing; the ledger is the right home |

Six new `MonitoringEventType` members total:
`OBLIGATION_RAISED`, `OBLIGATION_RESOLVED`, `OBLIGATION_DISMISSED`,
`PROPOSAL_CREATED`, `PROPOSAL_DECIDED`, `PROPOSAL_EXECUTED`. Added once, in
the joint Phase 0 commit, to `monitoring_enums.py` — the only touch that
file receives in this phase.

---

## 13. API Contract

Inspected and matched: `api/monitoring_routes.py`'s conventions —
`_context(request)`, `_now(supplied)`, `_fail(status, code, message,
details)`, `_handle(exc: MonitoringError)`, a per-router `_STATUS_BY_CODE`
dict, `response_model=` set explicitly to the bare canonical Pydantic model
(never a bespoke response wrapper). New router:
`backend/app/api/obligation_routes.py`, `APIRouter(prefix="/obligations",
tags=["obligations"])`, mounted in `main.py` beside the existing two.
**Authorization: none in this phase** — matching every existing route in the
repository, which has no auth layer at all. `reviewer` / `approved_by` are
free-text fields supplied by the caller, exactly as `reviewer` already is on
`RecordInvestigatorReviewRequest`. This is a known, accepted gap in a
hackathon prototype, not a new one this feature introduces.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/obligations` | List. Query: `trial_id` (required), `patient_id`, `status`, `type`, `party_id` |
| `GET` | `/obligations/queue` | The sorted, UI-ready read model |
| `GET` | `/obligations/{id}` | One obligation, with evidence |
| `GET` | `/obligations/{id}/actions` | The follow-up ledger, `seq` order |
| `POST` | `/obligations/{id}/investigate` | Run the agent; returns the created `ProposedAction` |
| `POST` | `/obligations/{id}/dismiss` | Human-only terminal transition |
| `GET` | `/obligations/proposals/{id}` | One proposal, with provenance |
| `POST` | `/obligations/proposals/{id}/approve` | The approval boundary |
| `POST` | `/obligations/proposals/{id}/reject` | Terminal, non-destructive |
| `GET` | `/obligations/parties` | The party registry, for the UI |

Proposals are nested under `/obligations/proposals/...` rather than a
sibling top-level router, to keep this Phase 0 addition to exactly one new
router file and one new context field.

### `GET /obligations?trial_id=CT-001&status=OPEN`

Request: query params only, no body.

```json
{
  "trial_id": "CT-001",
  "count": 1,
  "obligations": [
    {
      "obligation_id": "OB-4a91c07b2e",
      "obligation_key": "CT-001|P-3311|MISSING_LAB_EVIDENCE|INC-04|",
      "trial_id": "CT-001",
      "patient_id": "P-3311",
      "type": "MISSING_LAB_EVIDENCE",
      "status": "OPEN",
      "priority": "HIGH",
      "requirement_ref": "INC-04",
      "requirement_text": "eGFR at least 45 mL/min",
      "protocol_id": "CT-001",
      "source_ref": "SR-8f1e2c9a4d",
      "title": "Renal panel (eGFR) required by INC-04 is not on file",
      "detail": "Screening criterion INC-04 could not be evaluated: no eGFR result is recorded for this patient.",
      "evidence": [
        { "source_type": "RULE", "locator": "INC-04", "snippet": "eGFR at least 45 mL/min", "note": "Inclusion criterion, unresolved." }
      ],
      "first_detected_at": "2026-09-01T08:00:00Z",
      "last_confirmed_at": "2026-09-06T08:00:00Z",
      "due_at": null,
      "responsible_party_id": "SITE-03",
      "escalation_count": 0,
      "action_count": 1,
      "last_action_at": "2026-09-01T08:00:00Z",
      "resolved_at": null,
      "resolution": null
    }
  ]
}
```

`422 VALIDATION_ERROR` if `trial_id` is omitted — matches FastAPI's own
`RequestValidationError` path, already handled globally in `main.py`.

### `POST /obligations/OB-4a91c07b2e/investigate` → `201`

Request body: empty (`{}`) — every input the agent needs is already on the
obligation and reachable through the read facade; nothing is supplied by the
caller, matching the "requests exist only where the client holds less than
the model does" rule in §2.

Response — identical in shape to the prior plan's example, restated here as
the frozen contract:

```json
{
  "proposal_id": "PA-7c3d09e14b",
  "obligation_ids": ["OB-4a91c07b2e"],
  "trial_id": "CT-001",
  "patient_ids": ["P-3311"],
  "action_type": "REQUEST_LAB_EVIDENCE",
  "status": "DRAFT",
  "recipient_party_id": "SITE-03",
  "channel": "EMAIL",
  "subject": "CT-001 / P-3311 — renal panel (eGFR) outstanding for INC-04",
  "body": "Screening for P-3311 on CT-001 cannot complete because no eGFR result is on file for inclusion criterion INC-04 (eGFR at least 45 mL/min). Please provide the most recent renal panel at your earliest convenience.",
  "reason": "INC-04 resolved UNKNOWN: no eGFR result is on file. First request; no prior communication about this requirement.",
  "evidence": [
    { "source_type": "RULE", "locator": "INC-04", "snippet": "eGFR at least 45 mL/min", "note": "Inclusion criterion, unresolved." },
    { "source_type": "PDF_FIELD", "locator": "labs", "snippet": "HbA1c 7.8 %", "note": "Only lab on file; no renal panel." }
  ],
  "provenance": {
    "generated_by": "agent:gemini-3.x@prompt-v1",
    "model_name": "gemini-3.x",
    "prompt_version": "prompt-v1",
    "tools_called": ["get_obligation", "get_protocol_requirement", "get_screening_criterion", "get_patient_labs", "get_previous_communications", "get_responsible_party"],
    "evidence_ids": ["INC-04", "labs"],
    "degraded": false,
    "unresolved": []
  },
  "created_at": "2026-09-06T09:02:11Z",
  "decision": null,
  "execution": null
}
```

Errors: `422 OBLIGATION_TERMINAL` (obligation is `RESOLVED`/`DISMISSED`),
`422 PROPOSAL_PENDING` (an undecided `DRAFT` already exists for this
obligation), `404 OBLIGATION_NOT_FOUND`.

### `POST /obligations/proposals/PA-7c3d09e14b/approve`

Request:

```json
{
  "reviewer": "Dr. Anjali Rao",
  "note": "Reviewed against the protocol; wording is accurate, approving as drafted.",
  "edited_subject": null,
  "edited_body": null
}
```

Response: the `ProposedAction`, `status: "EXECUTED"`, `decision` and
`execution` both populated:

```json
{
  "proposal_id": "PA-7c3d09e14b",
  "status": "EXECUTED",
  "decision": {
    "outcome": "APPROVED",
    "reviewer": "Dr. Anjali Rao",
    "note": "Reviewed against the protocol; wording is accurate, approving as drafted.",
    "decided_at": "2026-09-06T09:10:04Z",
    "edited_subject": null,
    "edited_body": null
  },
  "execution": {
    "executed_at": "2026-09-06T09:10:04Z",
    "provider": "in-app-mock",
    "notification_id": "NT-2b6f0a1c88",
    "error": null
  }
}
```

(Full obligation/proposal fields omitted above for brevity; the response is
the complete `ProposedAction` model, per the "responses are bare canonical
models" rule.)

Errors: `422 REVIEWER_REQUIRED` / `422 REVIEW_NOTE_REQUIRED` (blank fields),
`422 PROPOSAL_NOT_DRAFT` (already decided), `404 PROPOSAL_NOT_FOUND`.
`approve()` calling `execute()` synchronously and folding a delivery failure
into `status: "FAILED"` rather than a separate `POST .../execute` step is a
deliberate simplification for this phase — see §18's entry on execution
failure for what the researcher sees when that happens.

### `GET /obligations/queue?trial_id=CT-001`

```json
{
  "trial_id": "CT-001",
  "generated_at": "2026-09-06T09:00:00Z",
  "counts": { "total": 1, "needs_decision": 0, "awaiting_response": 0 },
  "items": [
    {
      "obligation_id": "OB-4a91c07b2e",
      "patient_id": "P-3311",
      "type": "MISSING_LAB_EVIDENCE",
      "status": "OPEN",
      "priority": "HIGH",
      "title": "Renal panel (eGFR) required by INC-04 is not on file",
      "responsible_party": { "party_id": "SITE-03", "display_name": "Site 03 — Coordinator" },
      "age_days": 5,
      "escalation_count": 0,
      "pending_proposal_id": null,
      "needs_human_decision": false
    }
  ]
}
```

---

## 14. Service / Module Boundaries

The brief's proposed structure is validated against the actual repository
layout and accepted with one addition (`facade.py`, needed to make the
agent-boundary rule in §9 enforceable rather than aspirational):

```
backend/app/monitoring/obligations/
    detectors/
        screening_labs.py           # pure: ScreeningResult -> DetectedRequirement[]
        monitoring_observations.py  # pure: MonitoringCycleResult -> DetectedRequirement[]  (Phase 10, not Phase 1)
    rules.py                        # obligation_key(), priority_for(), transition validation
    reconcile.py                    # pure: detected + existing -> ObligationDelta
    service.py                      # ObligationService: persistence, ledger, timeline milestones
    parties.py                      # ResponsibleParty registry + resolve()
    proposals.py                    # ObligationProposalService: propose/validate/approve/reject
    execution.py                    # ExecutionService: execute(ApprovalRecord) only
    queue.py                        # build_queue(): the read model, pure function

backend/app/agent/
    facade.py                       # TrialReadFacade — the read-only surface agent/ is allowed
    tools.py                        # the typed tool registry, over the facade
    evidence.py                     # deterministic evidence-pack assembly
    prompts.py                      # SYSTEM_PROMPT, PROMPT_VERSION, banned-phrase list
    investigate.py                  # investigate(obligation_id) -> InvestigationOutput
    classify.py                     # (Phase 13) inbound response classification

backend/app/repository/
    obligation_base.py              # ObligationRepository ABC
    json_obligations.py             # JSON implementation

backend/app/schema/
    obligation_enums.py             # new enums, §4
    obligations.py                  # new models, §3

backend/app/api/
    obligation_routes.py            # new router, §13
    obligation_models.py            # request bodies only (approve/dismiss/reject payloads)
```

**"One obvious place for each responsibility," checked:** detection is pure
and knows nothing of persistence; reconciliation is pure and knows nothing
of detection *or* persistence; the service is the only thing that touches
the repository and the timeline; the agent is the only thing that touches an
LLM; the proposal service is the only thing that validates and stores a
draft; execution is the only thing that can call a delivery provider. No two
modules in this list share a reason to change.

This maps onto `MonitoringContext`
([`monitoring/context.py`](../backend/app/monitoring/context.py)) by adding
exactly one field — `obligations: ObligationContext` — following the
dataclass's existing `.build()` classmethod pattern, with `ObligationContext`
bundling `ObligationRepository`, `ObligationService`, `ObligationProposalService`,
`ExecutionService`, and `PartyRegistry` the same way `MonitoringContext`
bundles its own four services today.

---

## 15. Missing-Lab Detector Contract

**Input:** `ScreeningResult` (the actual existing object — confirmed against
`schema/result.py`; no new input type is needed).

**Output:** `list[DetectedRequirement]`.

```python
class DetectedRequirement(BaseModel):
    type: ObligationType
    trial_id: str
    patient_id: str
    requirement_ref: str
    requirement_text: str
    protocol_id: str
    source_ref: str
    evidence: list[Evidence]
    occurrence: str = ""
    due_at: datetime | None = None
```

**Exact detection rule**, read off `engine/eligibility.py` and
`engine/evaluators.py` as they exist today, not as re-derived from
description:

```python
def detect(result: ScreeningResult) -> list[DetectedRequirement]:
    found = []
    for cr in result.criteria_results:
        if cr.status is not CriterionStatus.UNKNOWN:
            continue
        criterion = next(c for c in result.trial.criteria if c.criterion_id == cr.criterion_id)
        rule = criterion.rule
        if not isinstance(rule, NumericRule) or not rule.field.startswith(LAB_PREFIX):
            continue   # UNKNOWN for a non-lab reason is not this detector's obligation type
        found.append(DetectedRequirement(
            type=ObligationType.MISSING_LAB_EVIDENCE,
            trial_id=result.trial.trial_id,
            patient_id=result.patient.patient_id,
            requirement_ref=cr.criterion_id,
            requirement_text=criterion.describe_expected(),
            protocol_id=result.trial.trial_id,
            source_ref=result.result_id,
            evidence=list(cr.evidence),
        ))
    return found
```

Precisely how `lab:eGFR → UNKNOWN → MISSING_LAB_EVIDENCE` happens: `evaluate_rule`
(`engine/evaluators.py`) resolves `field="lab:eGFR"` against
`Patient.labs`, finds no matching `LabResult`, and returns
`Evaluation(match=None)` ([`evaluators.py:44`](../backend/app/engine/evaluators.py#L44));
`apply_inversion(kind, None)` (`engine/eligibility.py`) maps any `None` match
to `CriterionStatus.UNKNOWN` regardless of `INCLUSION`/`EXCLUSION`; the
detector above then filters for exactly this status plus the `NumericRule` /
`lab:` field shape, which is the only signal distinguishing "we don't have
the evidence to check this" from "we checked and it failed" (a `FAIL` status
is never a `DetectedRequirement` — that is a real, resolved verdict, not a
missing-evidence gap, per the §19 acceptance scenarios).

**A `PresenceRule`-based `UNKNOWN` (e.g. an unrecognized condition or
medication) is explicitly out of scope for this detector.** It is a
different kind of evidence gap (`INCOMPLETE_EVIDENCE`, not built this phase)
and lumping it into `MISSING_LAB_EVIDENCE` would make the obligation's own
`title` inaccurate.

**Call site:** `ScreeningService.screen()`
([`service.py`](../backend/app/service.py)), immediately after
`repository.save_screening_result(result)`, wrapped in `try/except Exception`
— logged, never re-raised, so a detector defect can never turn a successful
screening into a failed one.

---

## 16. Failure Semantics

| Failure | Outcome | Enforced in |
|---|---|---|
| Detector raises | Screening/cycle completes normally; error logged; **`reconcile()` is never called for this scope**, so nothing is touched or resolved | call site `try/except` |
| Repository write fails | `RepositoryError` → existing `503 PERSISTENCE_FAILED` envelope, unchanged from Phase 1/2 | `json_obligations.py`, reusing `repository/base.py::RepositoryError` |
| Agent call fails (network, timeout, no API key) | `investigate()` returns a deterministic-template `ProposedAction` with `provenance.degraded = True`; the queue item still appears | `agent/investigate.py` |
| LLM output fails Pydantic validation | Same fallback as above; the raw invalid output is logged, never shown to the researcher | `agent/investigate.py` |
| Evidence is missing for a tool call | The pack records the gap; investigation proceeds with what it has; the specific gap is named in `provenance.unresolved` | `agent/evidence.py` |
| Evidence conflicts | Never auto-resolved — named in `unresolved`, left for the researcher, matching the existing `Disagreement` / `CONFLICTING_OBSERVATIONS` stance elsewhere in the codebase | `agent/evidence.py` |
| Proposal validation fails (banned phrase, oversize, unknown recipient) | The draft is replaced by the deterministic template, `degraded=True`, reason recorded in `unresolved` — **never silently dropped** | `proposals.py::validate_draft` |
| A second `investigate()` is called while a `DRAFT` is pending | `422 PROPOSAL_PENDING` — the researcher gets one thing to decide at a time | `proposals.py::propose` |
| Approval is rejected | `ProposalStatus.REJECTED`, retained and visible in history; obligation status is **unchanged**; a fresh `investigate()` may be requested | `proposals.py::reject` |
| Execution fails (provider error) | `ProposalStatus.FAILED`, `execution.error` populated, `DELIVERY_FAILED` ledger entry; obligation stays in its current status (does **not** advance to `AWAITING_RESPONSE`); **no automatic retry** — a new `investigate()` produces an independent `DRAFT` | `execution.py` |
| Duplicate detection (same key, re-run) | `TOUCH`, never a second `CREATE` — the entire point of §7 | `reconcile.py` |
| Duplicate proposal (`execute()` called twice on the same `EXECUTED` proposal) | No-op, returns the existing `ProposalExecution` unchanged | `execution.py::execute` |
| Notification provider fails | Identical to "execution fails" above — the provider's own failure is exactly what `execute()` catches | `execution.py`, via `deliver_with_outcome` (§11 of the prior plan) |
| Inbound response cannot be mapped to any obligation | Stored as an unattached, classified record; surfaced as "unmatched reply"; **never guessed onto an obligation** | `api/obligation_routes.py` (Phase 13) |
| Obligation is already terminal and a mutating call arrives | `422 OBLIGATION_TERMINAL` from every one of `investigate`, `dismiss`, and (indirectly, via the proposal) `approve`/`reject` | `service.py`, checked before any of the above proceed |

**The pattern throughout, stated once:** every failure produces either a
usable, explicitly-marked artifact (`degraded=True`, a `FAILED` status, an
`unresolved` entry) or a structured error. Nothing fails into a state that
*looks* like success — the same discipline `UNKNOWN`-is-not-fine already
enforces everywhere else in this codebase.

---

## 17. Vertical Slice Acceptance Test

The brief's 18-step list is the right shape and is adopted with one
reordering (evidence-conflict and duplicate checks are folded into the
existing steps rather than listed separately, since §16 already owns
failure semantics) and one addition (step 0, proving the *baseline* fact the
whole slice depends on):

```
 0. Baseline: screening P-3311 against CT-001 today (no obligation code
    active) already produces overall_status=REVIEW_REQUIRED with INC-04's
    CriterionResult.status == UNKNOWN. [proves the detector has real input]

 1. Screening P-3311/CT-001 with obligation detection active raises exactly
    one Obligation: type=MISSING_LAB_EVIDENCE, requirement_ref="INC-04",
    status=OPEN.

 2. Re-running the same screening three more times leaves exactly one
    Obligation row for this key — first_detected_at unchanged,
    last_confirmed_at advanced each time.

 3. GET /obligations?trial_id=CT-001&patient_id=P-3311 returns that one
    obligation with its evidence populated from CriterionResult.evidence.

 4. GET /obligations/queue?trial_id=CT-001 lists it with priority, title,
    and needs_human_decision=false (no draft yet).

 5. POST /obligations/{id}/investigate returns 201 with a ProposedAction,
    status=DRAFT, recipient_party_id resolved (not null, given parties.json
    seeds a Site 03 coordinator for CT-001), provenance naming the tools
    called.

 6. With GEMINI_API_KEY unset, step 5 still returns 201 with a usable draft
    and provenance.degraded=true.

 7. A second POST /obligations/{id}/investigate before the first draft is
    decided returns 422 PROPOSAL_PENDING.

 8. POST /obligations/proposals/{id}/approve without a reviewer returns 422
    REVIEWER_REQUIRED; without a note returns 422 REVIEW_NOTE_REQUIRED.

 9. POST /obligations/proposals/{id}/approve with reviewer+note returns 200,
    status=EXECUTED, decision and execution both populated, and — critically
    — a unit test asserts execute() itself has no accessible code path that
    accepts anything other than an ApprovalRecord (this is a type-level
    property, tested by attempting to call it with a bare ProposedAction and
    asserting a type error / assertion, not an HTTP test).

10. The obligation is now status=AWAITING_RESPONSE. GET .../actions shows,
    in seq order: DETECTED, PROPOSAL_CREATED, PROPOSAL_APPROVED,
    MESSAGE_SENT.

11. Calling execute() a second time against the same (already-executed)
    approval/proposal is a no-op: no second Notification, no second
    MESSAGE_SENT entry, execution timestamp unchanged.

12. POST /obligations/{id}/responses {text: "Renal panel drawn yesterday,
    uploading shortly", from_party_id: "SITE-03"} is classified and appended
    to the ledger as RESPONSE_RECEIVED. The obligation's status, resolution,
    and every other field are byte-identical before and after this call —
    the assertion that inbound text changes no clinical or lifecycle state.

13. An eGFR LabResult (value=52, unit="mL/min") is added to P-3311 and
    screening is re-run.

14. INC-04 now resolves to PASS (assuming 52 clears the >=45 threshold), so
    it is no longer UNKNOWN, so the detector no longer reports it.

15. The obligation transitions OPEN-lineage → RESOLVED (specifically:
    AWAITING_RESPONSE → RESOLVED, since step 9 already moved it out of
    OPEN), resolution.kind=SATISFIED, resolution.by="SYSTEM".

16. GET .../actions shows a final RESOLVED entry.

17. The full chain — requirement, detection, investigation provenance,
    approval, execution, response, resolution — is reconstructable by
    reading /obligations/{id}/actions plus
    /monitoring/patients/P-3311/timeline, with no information available
    only in application logs.
```

**Is this the right first acceptance test?** Yes, with one caveat worth
stating rather than hiding: step 14's specific eGFR value (52) is arbitrary
and must be picked to clear `INC-04`'s actual threshold
(`gte 45`) — the test fixture author must set a value that unambiguously
passes, not one that merely differs from "missing." This is a one-line
fixture detail, not an open architectural question, and is noted here so it
is not rediscovered as a surprise during implementation.

---

## 18. Open Decisions

Two of the five decisions raised in the prior planning pass are resolved
above (§7's protocol-version question, §9's tools-vs-packed question). Three
remain genuinely open and must be answered by the two developers before
Phase 1 begins — not because the answer is unclear, but because each is a
judgment call this document cannot make on their behalf.

**1. Should obligations replace cycle-generated notifications, or run
beside them?**
*Why it matters:* `MonitoringService.run_cycle()` today generates a fresh
`Notification` on every AMBER/RED cycle regardless of whether the same
condition was already notified last cycle — the exact spam behavior this
whole feature exists to fix. Once `MISSING_REQUIRED_OBSERVATION` obligations
exist (Phase 10), the *correct* long-term state is that obligations are the
only source of clinician-facing notifications and `build_notifications` in
`notifications.py` is retired or narrowed.
*Recommended:* run beside, for this phase. Do not touch `run_cycle`'s
existing notification path at all when adding the monitoring-side detector.
*Alternative:* retire `build_notifications` now and route everything through
obligations.
*Consequence of the alternative:* couples this feature's success to a
migration of existing, working, tested behavior, inside the same build
window — directly risking the Phase 2 monitoring demo, which does not
depend on obligations at all today.

**2. What is `AGENT_MODE`'s default, and is the team comfortable describing
it accurately?**
*Why it matters:* `packed` (one fixed tool sequence, one LLM call) and
`tools` (function-calling loop, capped at 8 calls) produce materially
different demo-day risk profiles and materially different claims about what
"the agent" is doing.
*Recommended:* `packed` as the default and the only mode built in this
phase; describe it to evaluators exactly as it is — "a fixed evidence
pipeline plus one structured reasoning call" — not as an autonomous agent
loop.
*Alternative:* build `tools` mode as well, this phase.
*Consequence of the alternative:* real value (a more impressive, and more
honest, claim if it works) traded against real risk (nondeterministic
tool-call sequences are the single hardest thing in this entire plan to get
demo-stable, and Phase 9 is already the latest phase before the two cuttable
ones).

**3. Where does `site_id` get seeded — per patient or per trial — for the
demo data?**
*Why it matters:* `parties.resolve()` needs `TreatmentAssignment.site_id` to
have a real value for the "Site 03 owes the renal panel" story to be
concrete rather than abstract. Screening fixtures currently carry no site
concept at all.
*Recommended:* seed per patient in the demo cohort generator (multiple
sites, so the population-view "Site 04 is trending" story is available
later), rather than one site per trial (which would make every party
resolution identical and the population view meaningless).
*Alternative:* one site per trial, simpler to seed.
*Consequence of the alternative:* the population-level-view phase (§13 of
the prior plan) has nothing to differentiate by site, weakening exactly the
feature the evaluator explicitly asked for.

One item is not a decision but a verification task with a hard deadline:
**confirm `gemini-3.5-flash` (or whichever model id `risk/xai_client.py`
actually names at build time) resolves against the live Gemini API before
Phase 9 begins.** The fallback path in `investigate()` means a bad model id
and a genuine outage are indistinguishable from the outside; verifying this
early converts a possible Phase 9 debugging session into a five-minute
check now.

---

## 19. Final Contract Summary

What is now frozen, and what a developer may build against without asking
the other:

- **Domain model** — §3, exact field lists, exact types, exact ownership.
- **Every enum and its home file** — §4, zero ambiguity about which file a
  given member lives in.
- **The obligation state machine** — §5, a transition table with no
  unstated cases.
- **The proposal state machine, kept separate** — §6, with the reasoning
  for the separation stated so neither developer re-merges them under
  schedule pressure.
- **Identity and deduplication** — §7, a pure function, worked example,
  and a closed decision on protocol versioning.
- **Reconciliation** — §8, three operations, exact field-level effects,
  and the scope guard that makes auto-resolve safe.
- **The agent boundary** — §9, structurally enforced via `agent/facade.py`,
  not left to code review discipline.
- **Read/write dependency table** — §10, one row per component, no
  component with two reasons to change.
- **Persistence** — §11, one new file, one new ABC, the exact JSON shape,
  no ORM.
- **Timeline integration** — §12, an exact kind-to-event mapping table.
- **API contract** — §13, every route, every example payload, every error
  code.
- **Module layout** — §14, one obvious place per responsibility.
- **The missing-lab detector** — §15, exact logic, traced through the real
  existing evaluator code, not re-derived.
- **Failure semantics** — §16, one row per failure mode, no unhandled case.
- **The acceptance test** — §17, 18 steps, end to end, with the one
  fixture caveat flagged.

What remains open — §18's three items — is exactly and only what requires a
judgment call this document cannot make, and each is scoped tightly enough
that answering it does not reopen anything else above.

**The next instruction can be exactly:** *"Implement Phase 1 according to
the Phase 0 Architecture Contract."*

---

## 20. R2 Amendments — local models, Gmail, WhatsApp

Added after the R2 revision ([`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md))
promoted local AI, Gmail and WhatsApp from future extensions to implementation
work. **Everything in §§1–19 above stands unchanged.** These are additive
deltas, each forced by a verified constraint of an external system rather than
by preference. Freeze them in the same Phase 0 commit as the rest.

### Amendment A — `ProposedAction` gains a template rendering (WhatsApp)

**Why:** Meta's Cloud API permits only pre-approved template messages for
business-initiated conversations outside a 24-hour user-initiated window
([IMPLEMENTATION_PLAN §0, Finding 1](IMPLEMENTATION_PLAN.md)). Every TrialGuard
message is business-initiated, so a model-drafted `body` is **not sendable over
WhatsApp at all**. Discovered now rather than in Phase 14.

```python
class ProposedAction(BaseModel):
    ...                                     # every existing field unchanged
    template_name: str | None = None        # NEW — approved Meta template id
    template_params: list[str] = Field(default_factory=list)  # NEW — ordered
```

| Field | Owner | Deterministic? | Set by the model? |
|---|---|---|---|
| `template_name` | `obligations/templates.py`, keyed on `ObligationType` | yes | **never** — an invented name would not be approved |
| `template_params` | `obligations/templates.py`, from obligation fields | yes | **never** — these are facts (patient id, requirement ref, trial id), not prose |

`subject` / `body` remain the canonical human-readable draft the researcher
reads and approves. Each provider **renders** its own wire format from the
approval: in-app uses subject+body verbatim, Gmail builds RFC 2822 from them,
WhatsApp uses `template_name` + `template_params` and ignores `body`.

**Consequence the UI must surface, not hide:** editing the email body does not
change what WhatsApp sends. The approval screen shows the rendered WhatsApp
message alongside the editable draft whenever WhatsApp is the selected channel.

### Amendment B — `ApprovalRecord` carries the rendering

**Why:** `ExecutionService.execute()` accepts only an `ApprovalRecord` (§3.D).
If the template fields were not on it, WhatsApp delivery would have to re-read
the proposal, which would reopen the exact hole the single-type signature
closes.

```python
class ApprovalRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    proposal_id: str
    approved_by: str
    approved_at: datetime
    channel: NotificationChannel
    subject: str                            # final, post-edit
    body: str                               # final, post-edit
    template_name: str | None = None        # NEW
    template_params: list[str] = Field(default_factory=list)  # NEW
```

Unchanged: constructible only by `ObligationProposalService.approve()`, only
after non-empty `reviewer` and `note`. **The invariant is untouched — no
external send exists without one of these.**

### Amendment C — `ProposalProvenance` distinguishes local from hosted

**Why:** §20 of the brief requires provenance to record which runtime answered.
A reproducibility trace that says "an LLM wrote this" without saying *which*,
*where*, and *how long it took* cannot answer "why did TrialGuard produce this
on date X".

```python
class ProposalProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)
    generated_by: str
    provider_kind: ProviderKind             # NEW — LOCAL | HOSTED | TEMPLATE
    model_name: str | None = None
    prompt_version: str | None = None
    latency_ms: int | None = None           # NEW
    tools_called: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    degraded: bool = False
    unresolved: list[str] = Field(default_factory=list)
```

### Amendment D — `ProposalExecution` records the channel and the provider's id

**Why:** the ledger must answer "which email/message was this" without querying
Gmail or Meta, and WhatsApp uniquely supplies real delivery confirmation via
status callbacks.

```python
class ProposalExecution(BaseModel):
    model_config = ConfigDict(frozen=True)
    executed_at: datetime
    provider: str
    channel: NotificationChannel                    # NEW
    notification_id: str | None = None
    provider_message_id: str | None = None          # NEW — Gmail id | wamid
    provider_thread_id: str | None = None           # NEW — Gmail threadId
    delivery_status: DeliveryStatus = DeliveryStatus.UNKNOWN   # NEW
    error: str | None = None
```

`delivery_status` starts `SENT` on a successful call and is advanced by WhatsApp
status callbacks. It stays `UNKNOWN` for channels that report nothing back — an
honest value, never defaulted to `DELIVERED`.

### Amendment E — `ResponsibleParty` gains a preferred channel

**Why:** open decision 6 in the R2 plan. A party the trial contacts by WhatsApp
and a party it emails are a property of the party, not a per-approval choice for
the researcher to re-make every time.

```python
class ResponsibleParty(BaseModel):
    ...                                             # existing fields unchanged
    preferred_channel: NotificationChannel = NotificationChannel.IN_APP  # NEW
```

The researcher may override at approval. `email` and `phone` are already on the
model (§3.E) and now carry real weight: `phone` must be in E.164 form for
WhatsApp.

### Amendment F — new enums, all in `obligation_enums.py`

The placement rule in §4 is unchanged: new vocabulary goes in the new file, and
`monitoring_enums.py` receives nothing beyond the six `MonitoringEventType`
members already specified.

| Enum | Members | Notes |
|---|---|---|
| `ProviderKind` | `TEMPLATE`, `LOCAL`, `HOSTED` | Model runtime class, for provenance |
| `DeliveryStatus` | `UNKNOWN`, `SENT`, `DELIVERED`, `READ`, `FAILED` | Mirrors WhatsApp's status vocabulary; `UNKNOWN` is the honest default for channels that report nothing |
| `ResponseIntent` | `WILL_PROVIDE`, `PROVIDED`, `DISPUTED`, `UNCLEAR` | Inbound classification output. Deliberately coarse — a four-way intent is all a human needs to triage a reply |
| `DetectorSource` | `SCREENING`, `MONITORING_OBSERVATION` | Referenced by `DetectionScope` in §8; formalised here |

**`NotificationChannel` is still not re-declared.** It already exists in
`monitoring_enums.py` with `IN_APP`, `EMAIL`, `SMS`, `PUSH`. R2 adds one member
to it — `WHATSAPP` — in the same Phase 0 commit as the six event types. That is
the **only** other change to that file, and it is additive per the file's own
docstring rule.

### Amendment G — one new `ObligationActionKind` member

`DELIVERY_STATUS_UPDATED`, appended to the 14 members in §4 (making 15). Raised
by a WhatsApp status callback. **Not** mirrored into the timeline — a
`delivered` receipt is not a patient-level milestone, and per §12's anti-
duplication rule it stays in the ledger only.

`RESPONSE_RECEIVED` already exists and is reused unchanged for both Gmail and
WhatsApp inbound.

### Amendment H — `NotificationDeliveryProvider` capability declarations

Extends the R1 addition of `deliver_with_outcome`. **Why:** `execution.py` must
be able to refuse a WhatsApp send with no `template_name` *before* an API call,
rather than discovering it from a Meta error code.

```python
class NotificationDeliveryProvider(ABC):
    name: str
    channel: NotificationChannel            # NEW
    supports_freeform: bool                 # NEW — False for WhatsApp
    requires_template: bool                 # NEW — True for WhatsApp
    def deliver(self, notification, now) -> Notification: ...          # existing
    def deliver_with_outcome(self, notification, approval, now) \
            -> tuple[Notification, DeliveryOutcome]: ...                # R1+R2
```

This is the **complete** extent of channel awareness inside the obligation
layer — one precondition check yielding `422 CHANNEL_REQUIRES_TEMPLATE`.
`obligations/` still never imports `comms/`; it receives a provider from
`comms/factory.py::build_delivery_provider(channel)`.

### Amendment I — `IncomingMessage`, and the clinical-write prohibition

```python
class IncomingMessage(BaseModel):
    model_config = ConfigDict(frozen=True)
    message_id: str
    channel: NotificationChannel
    provider_message_id: str
    provider_thread_id: str | None = None
    from_party_id: str | None = None        # None when unmatched
    obligation_id: str | None = None        # None when unmatched
    received_at: datetime
    body_text: str                           # UNTRUSTED — never a clinical value
    classification: ResponseIntent | None = None
    confidence: float | None = None
```

**Matching is deterministic and is never the model's job.** Priority order:
provider thread id against a stored `provider_thread_id`, then an opaque
obligation token in the subject line. No match → stored unattached, surfaced as
"unmatched reply", **and a `200 OK` is still returned to the webhook** so Meta
does not retry.

**The prohibition, restated as a structural fact:** `agent/classify.py` returns
a value object and holds no repository handle. The only write resulting from any
inbound message is one append-only `ObligationAction`. A reply asserting "the
eGFR is 52" creates **no** `LabResult` and resolves **no** obligation — an
obligation resolves only when a detector observes real evidence
(§8, auto-resolve). This is the single most important R2 safety property and it
is enforced by module boundaries, not by review discipline.

### Amendment J — configuration surface

Five tiers, all read once at startup via bare `os.environ.get()` exactly as
`RISK_PROVIDER` / `DATA_DIR` / `FRONTEND_ORIGIN` already are. **Tier 0 — nothing
set — must boot and pass every acceptance criterion except the Gmail and
WhatsApp steps.** Full variable list in
[IMPLEMENTATION_PLAN §11](IMPLEMENTATION_PLAN.md). Rules that are contract, not
preference:

1. No secret carries a value in `render.yaml`; every one is `sync: false`.
2. No secret is written into an `ObligationAction`, a `Notification`, or a log
   line. Ledger entries store `provider_message_id` and `responsible_party_id`,
   never an address or a phone number.
3. No credential ever gains a `VITE_` prefix — those are compiled into the
   browser bundle.

### What did NOT change

Stated explicitly, because the value of this contract is that a developer can
trust it: the `Obligation` model, the obligation state machine, the proposal
state machine, `obligation_key` and every deduplication rule, the reconciliation
contract and its scope guard, the agent's read-only boundary, the read/write
dependency table, the persistence contract, and the timeline anti-duplication
rule are all **unchanged by R2**. Three external systems were added to the
architecture without altering a single rule about what an obligation is or who
is allowed to decide anything.
