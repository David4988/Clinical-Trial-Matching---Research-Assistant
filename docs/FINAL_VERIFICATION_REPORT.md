# TrialGuard Final Verification Report

Date: 2026-09-07
Scope: full end-to-end audit of the working tree. Every claim below was
re-verified in this pass; prior reports were not taken on trust.

Architectural sources of truth: `docs/FINAL_IMPLEMENTATION_PLAN.md`,
`docs/PHASE0_CONTRACT.md`. No architecture was redesigned and no product
feature was added.

---

## 1. Overall status

**READY FOR DEMO**, with one external blocker (WhatsApp) that the primary
demo path does not depend on.

Two genuine defects were found and fixed. Everything else that was audited
was found already correct and was left alone.

| # | Defect | Fix | Evidence |
|---|--------|-----|----------|
| 1 | Demo recipient `coordinator@site03.example.org` is an RFC 2606 reserved domain with no MX. Gmail accepted the send, then bounced it asynchronously (~2s later). No message was ever delivered. | Replaced the SITE-03 email in `backend/fixtures/parties.json` — the single place it is seeded. | 201 historic `Delivery Status Notification (Failure)` messages, all naming `coordinator@site03.example.org`. |
| 2 | **The test suite performed real Gmail API sends.** `app/main.py` calls `load_dotenv('.env.local')` at import, so `comms/factory.py` returned a real `GmailProvider` inside `test_obligations_e2e.py`'s approve step. Every `pytest` run sent live email to a third party. | Added an autouse fixture in `backend/tests/conftest.py` clearing external credential env vars. Tests needing a configured provider set their own fakes via `monkeypatch.setenv`, so no assertion was weakened. | Controlled before/after against the live mailbox: a new SENT message appeared at 04:14:05 UTC during a test run; after the fix an identical run produced none. |

---

## 2. Test results

Command: `pytest tests -q` (from `backend/`, Python 3.11.15).

| Stage | Result |
|-------|--------|
| Baseline, before any change | **734 passed, 1 skipped** (81.6s) |
| After recipient fix | **734 passed, 1 skipped** (102.3s) |
| After hermetic-credentials fix | **734 passed, 1 skipped** (76.8s) |

0 failures, 0 regressions. No test was deleted, skipped, or weakened.

The single skip is `test_agent_local_provider_live.py` — a deliberate
opt-in live test, gated on `RUN_LIVE_LOCAL_MODEL_TESTS=1`.

---

## 3. Database verification

PostgreSQL 16 via `docker-compose.yml`, loopback-only on port 5433.
Migration cycle run against a scratch database (`tg_verify`, since dropped)
so demo data was never touched.

| Check | Result |
|-------|--------|
| Startup | Container healthy |
| `alembic upgrade head` from empty | All 4 revisions applied |
| `alembic check` | "No new upgrade operations detected" — no model drift |
| `alembic downgrade base` | Clean; only `alembic_version` remained |
| `alembic upgrade head` again | All 4 revisions re-applied |
| `alembic check` after round-trip | Clean |
| `PERSISTENCE=postgres` app | Full canonical loop passed (§4) |
| `PERSISTENCE=json` app | Full canonical loop passed — rollback path intact |

Constraints and indexes confirmed present in the live schema:

- `obligations_active_key` — **partial** unique index on `obligation_key`
  `WHERE status IN ('OPEN','AWAITING_RESPONSE')`. This is the unique
  obligation identity guarantee, and correctly permits re-opening after a
  resolution.
- `ledger_order` — `UNIQUE (obligation_id, seq)`: ledger ordering.
- `inbound_idempotent` — `UNIQUE (channel, provider_message_id)`: inbound
  idempotency.
- `ck_obligation_terminal_has_resolution` — a terminal status must carry
  `resolved_at`, `resolution_kind`, `resolution_by`, `resolution_note`.
- `researcher_is_named` — a `RESEARCHER` ledger actor must be named.

---

## 4. Core end-to-end acceptance

Canonical scenario **CT-001 / P-3311 / INC-04 / missing eGFR**, driven over
real HTTP against `PERSISTENCE=postgres`:

| Step | Observed |
|------|----------|
| Screen | `overall_status=REVIEW_REQUIRED`, `INC-04=UNKNOWN` before the obligation layer |
| Obligation | exactly 1, `MISSING_LAB_EVIDENCE`, `OPEN`, key `CT-001\|P-3311\|MISSING_LAB_EVIDENCE\|INC-04\|` |
| Re-screen ×4 | still exactly 1 — deduplication holds |
| Work Queue | 1 item |
| Evidence / requirement | present (`eGFR at least 45 mL/min`) |
| Ledger | `[DETECTED]` |
| Investigate | 201, `DRAFT`, channel `EMAIL`, recipient `SITE-03` |
| Duplicate investigate | 422 `PROPOSAL_PENDING` |
| Approve without reviewer | 422 `REVIEWER_REQUIRED` |
| Approve | 200, `EXECUTED`, delivery `SENT` |
| Re-approve | 422 `PROPOSAL_NOT_DRAFT` — no double send |
| Obligation | `AWAITING_RESPONSE` |
| Ledger | `[DETECTED, PROPOSAL_CREATED, MESSAGE_SENT, PROPOSAL_APPROVED]`, seq `1,2,3,4` — strictly increasing, no gaps |
| Add real eGFR + re-screen | `RESOLVED`, resolution `SATISFIED` by `SYSTEM` |
| Final ledger | `[DETECTED, PROPOSAL_CREATED, MESSAGE_SENT, PROPOSAL_APPROVED, RESOLVED]` |

The final state is reconstructable from the ledger alone.

---

## 5. Local AI verification

**Ollama was not reachable during this pass.** `http://127.0.0.1:11434`
returned no connection (curl `HTTP=000`); no SSH tunnel and no `ollama`
process was running, and no tunnel script exists in the repository.

Therefore a real `qwen3.5:9b` investigation latency could **not** be
measured in this pass, and the previously reported live verification is
neither confirmed nor contradicted here.

What was verified: with `MODEL_PROVIDER=local` and the endpoint down,
`build_model_provider()` falls back to `TemplateProvider` in **0.12s** —
fast, logged once, no hang and no startup failure. The SSH architecture was
not modified, no model was downloaded, and llama-server was not introduced.

---

## 6. Hosted AI verification

Provider: Gemini, configured model `gemini-3.6-flash`.

- Startup probe against the live API: **succeeded in 0.86s** — real
  credentials, real endpoint.
- A real investigation through the running app returned **HTTP 429
  `RESOURCE_EXHAUSTED`**: the free-tier quota
  (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 20/day) is
  exhausted for this key.

The degradation behaved exactly as designed, and this is the strongest
evidence in this report that the fallback contract holds under real failure:

- `degraded: true`, `provider_kind: TEMPLATE`, `generated_by: deterministic-template`
- the verbatim API error was recorded in `unresolved` rather than swallowed
- a valid, sendable proposal was still produced
- provenance honestly reported TEMPLATE, not the model

**Demo implication:** while the quota is exhausted, each hosted investigation
costs ~21s (the Google SDK's internal 429 backoff) and then degrades. Demo on
the Template provider, which is instant and deterministic.

---

## 7. Gmail verification

**Outbound — LIVE VERIFIED, message delivered.**

Full real chain: screen → obligation → investigate → proposal → approve →
`ExecutionService` → `GmailProvider` → Gmail API.

- Gmail message id `1a07a10e5bd8f0aa`, `From: davidson4988@gmail.com`,
  `To: maste005kar2005@gmail.com`, approve+execute in 1.53s.
- **Delivery confirmed**, not merely accepted: the thread contains exactly
  one message and zero Delivery Status Notifications after several minutes.
  The contrast is decisive — the previous `.example.org` send sat in a
  two-message thread whose second message was a mailer-daemon
  "Address not found" arriving **2 seconds** later.

**Inbound — LIVE VERIFIED at auth/transport; classification TEST VERIFIED.**

`POST /comms/gmail/poll` authenticated with the real refresh token and ran
its query (`is:unread label:trialguard`) in 893ms, returning
`fetched=0, matched=0, duplicates_skipped=0`. The mailbox holds no unread
labelled message, so retrieval → matching → classification was not exercised
against live content; that chain is covered by `test_comms_inbound.py`.

No OAuth secret was printed at any point.

---

## 8. WhatsApp verification

**EXTERNALLY BLOCKED.** No live send was attempted, and none should be
claimed. The exact blocker, from a read-only Meta Graph API check:

```
platform_type            : ON_PREMISE     <- not Cloud API
code_verification_status : NOT_VERIFIED
throughput.level         : NOT_APPLICABLE
message_templates        : (none)
```

Three independent blockers:

1. The number is registered on the **On-Premise API**, but the provider
   targets the **Cloud API** (`graph.facebook.com/.../messages`). A number
   registered ON_PREMISE cannot send via Cloud API until migrated.
2. The number is **not verified**.
3. **Zero message templates exist**, so template mode has nothing approved
   to send.

Additionally, no party in the registry has a phone number, so there is no
authorized test recipient. A recipient was never guessed. The access token
was never printed.

**Code — TEST VERIFIED.** Both delivery modes are implemented correctly:
business-initiated template mode, and customer-initiated session/free-form
mode gated on `ApprovalRecord.session_active`, which `approve()` resolves
deterministically from `has_active_whatsapp_session()` at approval time
(re-checked with the current clock, not inherited from the draft).
`ExecutionService` refuses to send when neither a template nor an active
session is available, before any API call.

**Inbound webhook security — TEST VERIFIED against a running server** (8/8):

| Case | Result |
|------|--------|
| Handshake, correct verify token | 200, bare `CHAL123` |
| Handshake, wrong token | 403 |
| Valid signature, unmatched message | 200 `{"matched": false}` |
| Invalid signature | 403 |
| Missing signature header | 403 |
| Malformed signature format | 403 |
| Tampered body with old signature | 403 |
| Valid signature, non-JSON body | 200 (no Meta retry storm) |

`verify_signature` uses `hmac.compare_digest` over the **raw** request body
before any JSON parsing, and fails closed on missing/malformed input. A
rejected webhook writes nothing.

---

## 9. Security verification

| Check | Result |
|-------|--------|
| Secrets in tracked files | None. High-signal scan (Google/OpenAI/Meta/OAuth/private-key patterns) clean. |
| Secrets in full git history | None. Same scan across `git log --all -p`. |
| `.env.local` | Untracked, ignored via `.gitignore:22` (`*.local`). |
| Frontend exposure | Only `VITE_API_BASE_URL` — an API origin, non-secret, documented as public. |
| Tokens in logs | No log statement in `app/comms/` interpolates a token, secret, key, or credential. |
| Credentials in fixtures / docs | None. |
| CORS | Explicit allow-list; never widened to `*`. |
| Webhook signature | Constant-time, raw-body, fails closed. |

**Model authority boundary.** The model cannot choose a recipient (resolved
from the party registry), alter protocol or eligibility truth (deterministic
rules are authoritative), modify clinical data, approve, send, or mutate
obligation state. Drafts pass `validate_draft` (banned phrases, length
ceiling, recipient must exist) and malformed output falls to the
deterministic template floor — observed live under the real 429 in §6.

---

## 10. Deployment verification

Graceful degradation confirmed by direct test — the app starts and serves in
every case:

| Condition | Behavior |
|-----------|----------|
| Ollama unavailable | Falls back to `TemplateProvider` in 0.12s, logged once |
| Hosted AI unavailable / no key | Falls back to `TemplateProvider` |
| Hosted AI quota exhausted | Per-request fallback, `degraded: true` |
| Gmail not configured | EMAIL falls back to in-app delivery |
| WhatsApp not configured | WHATSAPP falls back to in-app delivery |
| Unknown `MODEL_PROVIDER` | Warns, uses `TemplateProvider` |
| Database unreachable | Degrades to the JSON store rather than refusing to start |

Backend startup: **~1s** to serving under Postgres.

`GET /comms/health` reports the live provider map, so a silently degraded
deployment is visible.

---

## 11. Remaining external blockers

1. **WhatsApp / Meta** — number is ON_PREMISE not Cloud API, NOT_VERIFIED,
   and zero approved templates. Not fixable from this repository; requires
   Meta dashboard work. Details in §8.
2. **Gemini free-tier quota exhausted** (20 requests/day). Resets daily, or
   needs a billed key. Details in §6.
3. **Ollama tunnel not running** — no live local-model measurement was
   possible this pass. Details in §5.

None of these block the primary demo, which runs on Gmail + the Template
provider.

---

## 12. Known limitations

Recorded honestly; none were changed, as each is either by design or out of
scope for a final verification pass.

1. **Evidence sanitizer is a keyword denylist.** `templates.py` filters
   snippets on `("ignore", "override", "system:", "you are now",
   "disregard")`. This stops the known eval-harness injection but is
   bypassable by rephrasing. The real defense is architectural: deterministic
   rules own eligibility, and a human approves every outbound message before
   it sends.
2. **`ResponsibleParty.preferred_channel` no longer influences routing.**
   The email-first policy in `channel_policy.py` intentionally supersedes it.
   The field is still persisted and shown in the UI.
3. **Ledger orders `MESSAGE_SENT` before `PROPOSAL_APPROVED`** (seq 3 then
   4), though approval precedes the send in real time. Deterministic,
   consistent, and asserted by tests; noted rather than changed.
4. **`JsonObligationRepository.has_active_whatsapp_session` assumes
   timezone-aware timestamps.** A naive `received_at` raises `TypeError`.
   Not reachable from application code — every inbound path defaults to
   `datetime.now(timezone.utc)` — but a hand-edited `obligations.json` could
   trigger it. The Postgres path is unaffected (`DateTime(timezone=True)`).
5. **`app/risk/xai_client.py` uses `datetime.utcnow()`** (naive, deprecated).
   Confined to the risk-explanation path; not in the obligation ledger.
6. **Three stray scripts at the repo root** — `test_advance.py`,
   `test_advance_3.py`, `test_hours.py`. Tracked, outside `backend/tests/`,
   not collected by `pytest tests`. Left in place; removing them was out of
   scope for this pass.

---

## 13. Final demo instructions

```bash
# 1. PostgreSQL
docker compose up -d postgres

# 2. Backend
cd backend
source .venv/bin/activate
python -m alembic upgrade head
PERSISTENCE=postgres \
DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard" \
  python -m uvicorn app.main:app --port 8000

# 3. Frontend
cd frontend && npm install && npm run dev     # http://localhost:5173
```

Leave `MODEL_PROVIDER` unset for the demo: the Template provider is instant
(~40ms investigate) and deterministic. Gmail is configured from the
repo-root `.env.local` and needs no flag.

Demo path (all steps verified in §4 and §7):

1. Open TrialGuard → Work Queue
2. Show P-3311 / CT-001, missing eGFR obligation
3. Open the obligation → evidence and requirement text
4. Run investigation → `ProposedAction` DRAFT
5. Show provenance (provider, tools called, evidence ids, degraded flag)
6. Approve as a named reviewer with a note
7. Send lands through Gmail — show the real message
8. Show the ledger / history
9. Add the missing eGFR, re-screen
10. Show `RESOLVED`

Do not make WhatsApp part of the primary demo (§8).

Measured performance (Postgres, warm):

| Operation | Median |
|-----------|--------|
| `GET /health` | 1.0 ms |
| `GET /obligations` | 6.2 ms |
| `GET /obligations/parties` | 5.3 ms |
| `GET /obligations/queue` | 14.3 ms |
| `POST investigate` (Template) | 40 ms |
| `POST approve` + real Gmail send | 1.2–1.5 s |
| Backend startup | ~1 s |

No pathological behavior found; nothing was optimized.

---

## 14. Final verdict

| Component | Status |
|-----------|--------|
| PostgreSQL persistence | LIVE VERIFIED |
| JSON rollback persistence | LIVE VERIFIED |
| Alembic migrations (up / down / up / check) | LIVE VERIFIED |
| Obligation lifecycle | LIVE VERIFIED |
| Deterministic obligation identity | LIVE VERIFIED |
| Reconciliation / deduplication | LIVE VERIFIED |
| Follow-Up Ledger | LIVE VERIFIED |
| ResponsibleParty registry | LIVE VERIFIED |
| Missing Lab detector | LIVE VERIFIED |
| Monitoring Observation detector | TEST VERIFIED |
| Work Queue API | LIVE VERIFIED |
| Work Queue UI | CODE COMPLETE |
| ProposedAction / ApprovalRecord | LIVE VERIFIED |
| Human approval boundary | LIVE VERIFIED |
| In-App delivery | TEST VERIFIED |
| **Gmail outbound** | **LIVE VERIFIED — delivered** |
| Gmail inbound polling | LIVE VERIFIED (auth + retrieval); classification TEST VERIFIED |
| WhatsApp outbound (template + session) | EXTERNALLY BLOCKED |
| WhatsApp inbound webhook | TEST VERIFIED |
| Webhook signature validation | TEST VERIFIED |
| TemplateProvider | LIVE VERIFIED |
| LocalProvider / Ollama / qwen3.5:9b | DEFERRED — tunnel down this pass |
| HostedProvider (Gemini) | LIVE VERIFIED — probe live; generation quota-exhausted |
| Provider switching | LIVE VERIFIED |
| Fallback handling | LIVE VERIFIED — under a real 429 |
| Agent investigation | LIVE VERIFIED |
| Response classification | TEST VERIFIED |
| Population operations view | CODE COMPLETE |
| Timeline integration / provenance | LIVE VERIFIED |
| Evaluation harness / model comparison | CODE COMPLETE |
| Prompt-injection defenses | TEST VERIFIED (see §12.1) |
| Secret hygiene | LIVE VERIFIED |
| Graceful degradation | LIVE VERIFIED |
| Test suite (734 passed, 1 skipped) | LIVE VERIFIED |

**TrialGuard is READY FOR DEMO.**
