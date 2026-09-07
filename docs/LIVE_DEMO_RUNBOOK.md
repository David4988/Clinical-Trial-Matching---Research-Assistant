# TrialGuard — Live Demo Runbook

Written against the repository as it stands on 2026-09-07. Every command,
endpoint, port, button label and expected output below was traced in the code
or executed against a running instance. Where something does **not** work the
way you might expect, it says so.

**Status legend**

| Mark | Meaning |
|------|---------|
| 🟢 | LIVE VERIFIED — executed end-to-end against the real system |
| 🟡 | IMPLEMENTED BUT NOT LIVE VERIFIED — code traced, not proven live |
| 🔵 | LOCAL / DEMO ONLY — works, but it is demo scaffolding |
| 🔴 | BLOCKED — external dependency prevents it |

---

## 0. Five things that will bite you (read this first)

These are the non-obvious facts. Each one was verified, and each one can ruin
a live demo.

1. **The backend MUST run on port 8000.** `frontend/vite.config.ts` hardcodes
   a proxy `/api → http://127.0.0.1:8000`. Any other port and the whole UI
   shows `NETWORK_ERROR`.

2. **`pytest` destroys your demo data.** 🟢 `tests/db_support.py` sets
   `TEST_DATABASE_URL` to the *same* `trialguard` database the demo uses, and
   `reset_schema()` runs `DROP SCHEMA trialguard CASCADE`. Running the suite
   with Postgres up wipes every obligation, proposal and screening. Verified —
   this is exactly how the demo data got emptied during the verification pass.
   **Do not run pytest after you seed the demo.**

3. **The Screening tab cannot create the demo obligation.** Its "Use sample"
   button loads `SAMPLE_PATIENT` = **P-1042**, which *already has* eGFR 47
   (`frontend/src/api/sample.ts`). No missing evidence, no obligation. The
   canonical P-3311 obligation must be seeded with one `POST /screen` call.

4. **There is no "re-screen" button anywhere in the UI.** Resolution is driven
   by a second `POST /screen` call. Plan for one terminal command mid-demo.

5. **The channel dropdown offers WhatsApp, and picking it burns the
   proposal.** SITE-03 has no phone number, so it fails with
   `RECIPIENT_PHONE_MISSING`. Recoverable (see §12 Path C), but never touch
   that dropdown on stage.

6. **A backend may already be running on port 8000.** 🟢 At the time of
   writing there was a `uvicorn app.main:app --reload` process holding 8000 and
   serving **JSON**, started outside this session. A second `uvicorn` exits with
   `[Errno 48] address already in use` — and if you don't read the log you will
   happily demo against the wrong server. Always check §3.K *after* starting.

7. **Environment variables must reach the process.** `export VAR=… &` in a
   backgrounded chain silently did not apply during this write-up; the app came
   up on JSON with `persistence_degraded: false` (which means "JSON was
   chosen", not "Postgres failed"). Prefer the `env VAR=… uvicorn …` form, and
   confirm with `/health`.

8. **`backend/data/*.json` holds stale state.** 🟢 Those files survive every
   Postgres reset and are what the JSON fallback reads. At the time of writing
   `data/obligations.json` contained two leftover P-3311 obligations. If you
   ever fall back to JSON, clear them first (§5.6).

---

## 1. What actually exists (verified inventory)

| Capability | Status | Note |
|---|---|---|
| Deterministic screening → obligation detection | 🟢 | `POST /screen` runs the detector downstream |
| Obligation identity / dedup | 🟢 | Partial unique index; 4× screening → still 1 |
| Work Queue UI | 🟢 | Hardcoded to `CT-001` |
| Evidence + Follow-Up Ledger UI | 🟢 | Rendered with `#seq`, kind, actor, channel |
| Investigation → ProposedAction | 🟢 | Button label: **"Draft a request"** |
| Provenance badge in UI | 🟢 | `provider_kind`, `model_name`, `DEGRADED`, unresolved |
| Human approval (reviewer + note required) | 🟢 | Button: **"Approve & send"** |
| Gmail outbound, real delivery | 🟢 | Confirmed delivered, msg `1a07a10e5bd8f0aa` |
| Response → classification → ledger | 🟢 | Via `POST /obligations/{id}/responses` |
| Re-screen → RESOLVED | 🟢 | Resolution `SATISFIED` by `SYSTEM` |
| Failed-delivery recovery | 🟢 | Obligation stays OPEN, can re-draft |
| TemplateProvider | 🟢 | ~40 ms, deterministic, always available |
| Graceful degradation (all providers) | 🟢 | Verified for Ollama, Gemini, Gmail, DB |
| Trial Overview (population) | 🟢 | Patient counts only — **not** obligations |
| Obligations aggregate in overview API | 🟡 | Backend returns it; **UI never renders it** |
| Local Ollama / qwen3.5:9b | 🔴 *today* | Tunnel down at time of writing; see §4 |
| Hosted Gemini | 🔴 *today* | Free-tier quota exhausted; ~21 s then degrades |
| Gmail inbound polling | 🔴 | `trialguard` label does not exist; see §9 |
| WhatsApp outbound | 🔴 | Meta: ON_PREMISE, NOT_VERIFIED, 0 templates |

---

## 2. The demo story (5–8 minutes)

One patient, one missing lab, one loop that closes.

```
P-3311 screened against CT-001
   └─ INC-04 (eGFR ≥ 45) has no result        → UNKNOWN, not a guess
       └─ obligation MISSING_LAB_EVIDENCE      → OPEN
           └─ Work Queue: "what needs me now?"
               └─ Draft a request              → ProposedAction + provenance
                   └─ Human approves (named)   → the boundary
                       └─ Real Gmail send      → provider_message_id
                           └─ Coordinator replies → classified PROVIDED
                               └─ eGFR arrives → re-screen
                                   └─ RESOLVED (SATISFIED, by SYSTEM)
```

The line that ties it together: **rules decide, AI assists, humans approve.**

---

## 3. Pre-demo setup checklist

### A. MacBook setup

```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant
git status --short          # know what is uncommitted before you present
```

Close Slack/Mail/notifications. Set terminal font large enough to read.

### B. PC setup (only if demoing the local model)

See §4. If the tunnel is not up 15 minutes before, **abandon local AI** and
demo on TemplateProvider. That is Path B and it is a good demo.

### C. SSH / Ollama

See §4 for exact commands.

### D. PostgreSQL

```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant
docker compose up -d postgres
docker ps --format "{{.Names}} {{.Status}}"
```

Expect: `...postgres-1  Up ... (healthy)` on `127.0.0.1:5433`.

```bash
cd backend
source .venv/bin/activate
export DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard"
export MIGRATION_DATABASE_URL="$DATABASE_URL"
python -m alembic upgrade head
python -m alembic current
```

Expect: `4caba4bb846e (head)`.

### E. Gmail

Nothing to start. Credentials live in the git-ignored `.env.local` at the repo
root and are loaded by `app/main.py` via `load_dotenv`. Verify **without
printing secrets**:

```bash
cd backend && source .venv/bin/activate
python -c "
from dotenv import dotenv_values
v=dotenv_values('../.env.local')
for k in ('GMAIL_CLIENT_ID','GMAIL_CLIENT_SECRET','GMAIL_REFRESH_TOKEN','GMAIL_SENDER'):
    print(f'{k:22}', 'SET' if (v.get(k) or '').strip() else 'MISSING')
"
```

Expect four `SET` lines. **This prints no secret values.**

### F. Browser tabs

| Tab | URL | Purpose |
|-----|-----|---------|
| 1 | `http://localhost:5173` | TrialGuard — the only tab judges see |
| 2 | `https://mail.google.com` | Logged in as **maste005kar2005@gmail.com** (the recipient), inbox open |
| 3 *(hidden)* | `http://127.0.0.1:8000/docs` | Only if a judge asks to see the API |

Tab 2 is the money shot. Have it pre-loaded and pre-scrolled.

### G. Environment variables

The exact demo configuration:

```bash
export PERSISTENCE=postgres
export DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard"
# MODEL_PROVIDER deliberately UNSET → TemplateProvider (instant, deterministic)
```

`repository/factory.py` also infers `postgres` from a present `DATABASE_URL`,
but set `PERSISTENCE` explicitly so there is no ambiguity.

### H. Demo data

One command creates the entire demo state (see §5.4).

### I. Backend startup — Terminal 1

```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/backend

# make sure nothing already owns port 8000
lsof -nP -iTCP:8000 -sTCP:LISTEN        # expect NO output
# if something is listed:  kill <PID>

env PERSISTENCE=postgres \
    DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard" \
    .venv/bin/python -m uvicorn app.main:app --port 8000
```

The `env VAR=… .venv/bin/python` form is deliberate: it guarantees the
variables reach the process. 🟢 During this write-up an `export`-then-background
form silently did not, and the app came up on JSON.

Do **not** add `--reload` for the demo; a stray file save would restart it
mid-presentation. Expect `Application startup complete.` in about 1 second.
Then **always** run §3.K — do not assume it worked.

### J. Frontend startup — Terminal 2

```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/frontend
npm install     # first time only
npm run dev
```

Expect Vite on `http://localhost:5173`.

### K. Final health checks — Terminal 3

```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

Expected, exactly (🟢 captured from a live run):

```json
{
    "status": "ok",
    "phase": "1",
    "ai_provider": "mock-slm-v1",
    "repository": "SqlRepository",
    "persistence_backend": "postgres",
    "persistence_degraded": false,
    "obligations_enabled": true,
    "delivery_providers": {
        "IN_APP": "in-app",
        "EMAIL": "gmail",
        "WHATSAPP": "whatsapp"
    }
}
```

Check these four:
- `persistence_backend: "postgres"` — not `json`
- `persistence_degraded: false` — `true` means Postgres was unreachable
- `obligations_enabled: true` — `false` means no Work Queue
- `EMAIL: "gmail"` — `in-app-fallback` means Gmail creds did not load

> **Do not misread `ai_provider`.** That field is the Phase-2 **risk** provider
> (`mock-slm-v1`), *not* the agent model. The agent model is shown only on the
> proposal's provenance badge. A judge who spots "mock" and asks is a judge you
> can impress — see §16.

---

## 4. Local model over SSH (Ollama + qwen3.5:9b)

Traced from `app/agent/model/local_provider.py` and
`app/agent/model/factory.py`.

**Current state: 🔴 the tunnel was down when this runbook was written**
(`curl http://127.0.0.1:11434/api/tags` → connection failed). Treat local AI as
optional. The demo does not need it.

### 4.1 What must run on the PC

Ollama serving on all interfaces so SSH can reach it, with the model pulled:

```powershell
# On the PC (PowerShell)
ollama serve
ollama list                 # confirm qwen3.5:9b is present
```

If `ollama serve` says the port is in use, the background service is already
running — that is fine.

### 4.2 SSH command on the Mac

```bash
ssh -N -L 11434:127.0.0.1:11434 <pc-user>@<pc-host>
```

Leave this running in its own terminal. `-N` = no shell, just the tunnel.
Replace `<pc-user>@<pc-host>` with your actual login; this runbook does not
guess your hostname.

### 4.3 Port exposed on the Mac

`127.0.0.1:11434` — which is exactly `DEFAULT_LOCAL_ENDPOINT` in
`agent/model/factory.py`, so no override is needed.

### 4.4 Environment variables

```bash
export MODEL_PROVIDER=local
export LOCAL_MODEL_ENDPOINT="http://127.0.0.1:11434"   # default; optional
export LOCAL_MODEL_NAME="qwen3.5:9b"                   # default; optional
export AGENT_TIMEOUT_SECONDS=90                        # default
```

### 4.5 Test the connection before the demo

```bash
curl -s -m 5 -o /dev/null -w "HTTP=%{http_code}\n" http://127.0.0.1:11434/api/tags
```

`HTTP=200` → tunnel is up. `HTTP=000` → it is not. This is the same
`/api/tags` path `LocalProvider.probe()` uses.

### 4.6 Verify qwen3.5:9b is loaded

```bash
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; print([m['name'] for m in json.load(sys.stdin)['models']])"
```

The list must contain `qwen3.5:9b` — the exact string in `LOCAL_MODEL_NAME`.

### 4.7 What happens if the tunnel fails

Verified 🟢: `build_model_provider()` probes at startup, fails in **0.12 s**,
logs once, and returns `TemplateProvider`. The app starts normally and the
Work Queue behaves identically. A mid-demo tunnel drop degrades per-request:
the proposal still appears, with `DEGRADED` on the provenance badge.

### 4.8 Switching safely to TemplateProvider

```bash
# Terminal 1: Ctrl-C, then
unset MODEL_PROVIDER
python -m uvicorn app.main:app --port 8000
```

Unsetting is enough — `TEMPLATE` is the default. Restart takes ~1 second.

> **Recommendation:** demo on TemplateProvider. It is instant (~40 ms), never
> fails, and §8 gives you the language to present that as an engineering
> strength rather than an absence of AI.

---

## 5. Database

### 5.1 Which backend

**PostgreSQL**, local, via `docker-compose.yml`. Reasons, all verified:
real constraints (partial unique index for obligation identity, ledger
ordering, terminal-state CHECKs), and it is what the verification pass
exercised. Supabase is a deployment target documented in `docs/DEPLOYMENT.md`
— do not introduce it on demo day. JSON is the rollback (§12 Path D).

### 5.2 Startup and migration

See §3.D.

### 5.3 Verify

```bash
# reachable
docker exec clinical-trial-matching---research-assistant-postgres-1 \
  psql -U trialguard -d trialguard -c "SELECT 1;"

# migrations current
cd backend && source .venv/bin/activate
export DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard"
export MIGRATION_DATABASE_URL="$DATABASE_URL"
python -m alembic current          # → 4caba4bb846e (head)
python -m alembic check            # → No new upgrade operations detected.

# TrialGuard is actually using it
curl -s http://127.0.0.1:8000/health | python3 -m json.tool | grep persistence
```

### 5.4 Seed the canonical demo state 🟢

One command. Run it **after** the backend is up:

```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/backend
python3 - <<'PY'
import json, urllib.request
B = "http://127.0.0.1:8000"
patient = json.load(open("fixtures/patient_incomplete.json"))
trial   = json.load(open("fixtures/trial_demo.json"))
req = urllib.request.Request(B + "/screen", method="POST",
        data=json.dumps({"patient": patient, "trial": trial}).encode(),
        headers={"Content-Type": "application/json"})
res = json.load(urllib.request.urlopen(req))
inc4 = [c for c in res["criteria_results"] if c["criterion_id"] == "INC-04"][0]
print("overall :", res["overall_status"], "| INC-04:", inc4["status"])
q = json.load(urllib.request.urlopen(B + "/obligations/queue?trial_id=CT-001"))
print("queue   :", q["counts"])
PY
```

Expected output, exactly:

```
overall : REVIEW_REQUIRED | INC-04: UNKNOWN
queue   : {'total': 1, 'needs_decision': 0, 'awaiting_response': 0}
```

🟢 Verified on a clean Postgres. `needs_decision` is **0**, and that is correct:
`queue.py:56` sets `needs_human_decision` only when a DRAFT proposal is
pending. It becomes `1` after you click "Draft a request" in STEP 3 — the
queue then sorts decision-needing items to the top.

If `total` is more than 1, you have leftovers — reset (§5.5) and re-seed.

### 5.5 Safe reset before a rehearsal

This touches **only** the local throwaway Docker container defined in
`docker-compose.yml`. There is no production data involved.

```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/backend
source .venv/bin/activate
export DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard"
export MIGRATION_DATABASE_URL="$DATABASE_URL"

# stop the backend first (Ctrl-C in Terminal 1), then:
python -m alembic downgrade base
python -m alembic upgrade head
```

Then restart the backend and re-run §5.4. Party records re-seed automatically
on startup (`ObligationContext.build(seed_parties=True)`, an upsert).

### 5.6 Resetting the JSON store (only if you are on the JSON fallback)

`alembic downgrade` does **not** touch these files. They are git-ignored local
demo state, not production data.

```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/backend
# with the backend stopped:
rm -f data/obligations.json
```

`data/store.json` and `data/monitoring.json` hold screening and monitoring
history; leave them unless the queue is still wrong after removing
`obligations.json`. All three are regenerated on demand.

---

## 6. Gmail live demo

### 6.1 Where the recipient comes from

**`backend/fixtures/parties.json`**, party `SITE-03`, field `email` →
currently `maste005kar2005@gmail.com`.

Chain: `fixtures/parties.json` → `app/fixtures_loader.py::load_parties()` →
`ObligationContext.build(seed_parties=True)` → `repository.save_party()`
(a Postgres upsert, so a restart re-seeds it). Nothing is hardcoded in
`GmailProvider`; recipient resolution is entirely data-driven.

Sender is `GMAIL_SENDER` in `.env.local` → `davidson4988@gmail.com`.

### 6.2 Confirm the recipient without sending anything

```bash
curl -s http://127.0.0.1:8000/obligations/parties | python3 -c "
import sys,json
for p in json.load(sys.stdin): print(f\"{p['party_id']:8} {p['email']}\")"
```

Expect `SITE-03  maste005kar2005@gmail.com`.

### 6.3 Do not send during setup

The **only** action that sends an email is clicking **"Approve & send"** (or
`POST /obligations/proposals/{id}/approve`). Seeding, investigating, browsing
the queue and every health check send nothing. Verified 🟢.

Investigate freely during rehearsal; just never approve until you mean it.

### 6.4 Verifying the send after you approve

The UI shows it inline under PROPOSED ACTION:

```
Proposal PA-xxxxxxxx: EXECUTED via gmail (EMAIL) — SENT
```

For the `provider_message_id`:

```bash
curl -s http://127.0.0.1:8000/obligations/proposals | python3 -c "
import sys,json
p=[x for x in json.load(sys.stdin) if x.get('execution')][-1]
e=p['execution']
print('status :', e['delivery_status'])
print('provider:', e['provider'])
print('msg id :', e['provider_message_id'])
print('error  :', e['error'])"
```

Expect `SENT`, `gmail`, a 16-hex id, `error: None`.

Then switch to browser tab 2 and show the email in the inbox. **That is the
strongest 10 seconds of the demo — do not rush it.**

---

## 7. The demo script

Total: 6 minutes at a calm pace.

---

### STEP 1 — INTRODUCTION *(20 s)*

**What I say:**

> "Clinical trials don't usually fail because someone made a wrong decision.
> They fail because something was missing and nobody chased it. TrialGuard is
> a follow-up engine for exactly that gap. Let me show you one patient."

**What I do:**
1. Screen already on `http://localhost:5173`, **Work Queue** tab selected.

**Audience sees:** the queue with a single row.

**Expected result:** one item — P-3311, "Evidence required by INC-04 is not on
file", priority LOW, status OPEN.

---

### STEP 2 — THE OBLIGATION 🟢 *(45 s)*

**What I say:**

> "Screening P-3311 against trial CT-001 hit inclusion criterion four: eGFR at
> least 45. There's no eGFR on file. The system does not guess and it does not
> fail the patient — it records UNKNOWN, and it turns that unknown into a
> tracked obligation with an owner and a deadline."

**What I do:**
1. Click the queue row.

**Audience sees:** obligation detail — Patient P-3311, Requirement INC-04
(CT-001), Priority, Escalations; an **EVIDENCE** block; a **FOLLOW-UP LEDGER**
showing `#1 DETECTED`.

**Technical point:** the obligation key is
`CT-001|P-3311|MISSING_LAB_EVIDENCE|INC-04|`, and a partial unique index in
Postgres enforces one active obligation per key. Screening the same patient
four times produces one obligation, not four.

---

### STEP 3 — INVESTIGATION 🟢 *(60 s)*

**What I say:**

> "Now I ask the system to prepare the follow-up. This is where the AI sits —
> and notice where it *doesn't* sit."

**What I do:**
1. Click **"Draft a request"**.

**Audience sees:** a PROPOSED ACTION panel with a provenance badge, a channel
selector reading **Email**, the recipient (Site 03 — Coordinator, with the
email address), and a drafted subject and body.

**Expected result** (TemplateProvider):

```
CT-001 / P-3311 — Evidence required by INC-04 is not on file

Screening for P-3311 against CT-001 cannot complete because requirement
INC-04 (eGFR at least 45 mL/min) has no result on file.

Relevant record note: eGFR >= 45 mL/min

Could you confirm whether the result is available and provide it?
```

**Technical point:** deliver §8 here.

> ⚠️ **Do not touch the channel dropdown.** See §0.5.

---

### STEP 4 — HUMAN APPROVAL 🟢 *(45 s)*

**What I say:**

> "Nothing leaves this system without a named human. The reviewer and the note
> are both mandatory — the API rejects an approval without them, and both go
> into the permanent record."

**What I do:**
1. Type `Dr. Rao` into **Reviewer**.
2. Type `Reviewed and accurate.` into **Note**.
3. Click **"Approve & send"**.

**Audience sees:** the panel updates to
`Proposal PA-…: EXECUTED via gmail (EMAIL) — SENT`, and the ledger grows.

**Technical point:** approval and delivery are separate records. The
`ApprovalRecord` stores what the human authorised; `ProposalExecution` stores
what the transport actually did, including the provider's message id.

**Expected result:** ledger reads
`#1 DETECTED · #2 PROPOSAL_CREATED · #3 MESSAGE_SENT · #4 PROPOSAL_APPROVED`,
and the obligation moves to `AWAITING_RESPONSE`.

---

### STEP 5 — REAL EMAIL 🟢 *(30 s)*

**What I say:**

> "That's not a simulation. That's the Gmail API."

**What I do:**
1. Switch to browser tab 2 (the coordinator's inbox).
2. Point at the message.

**Audience sees:** the actual email, subject
`CT-001 / P-3311 — Evidence required by INC-04 is not on file`.

**Technical point:** Gmail is one implementation of a delivery-provider
interface. WhatsApp and in-app implement the same interface; the obligation
engine has no idea which one answered.

---

### STEP 6 — THE RESPONSE 🟢 *(45 s)*

**What I say:**

> "The coordinator replies. The system reads that reply, classifies the
> intent — and critically, changes no clinical data on the strength of it."

**What I do:** run this in Terminal 3 (have it typed and ready):

```bash
OID=$(curl -s "http://127.0.0.1:8000/obligations?trial_id=CT-001" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['obligations'][0]['obligation_id'])")
curl -s -X POST "http://127.0.0.1:8000/obligations/$OID/responses" \
  -H "Content-Type: application/json" \
  -d '{"text":"Thanks - the renal panel is back. The eGFR result is attached.","from_party_id":"SITE-03"}' \
  | python3 -m json.tool | head -20
```

3. Return to the browser, click **← Back to queue**, then re-open the item.

**Audience sees:** a new ledger line
`RESPONSE_RECEIVED … · classified: PROVIDED`.

**Expected result:** classification `PROVIDED`, confidence `0.7`. **Obligation
status is still `AWAITING_RESPONSE` — unchanged by the text.** 🟢

**Technical point:** classification is a label on a message, never a state
transition. An email cannot resolve an obligation; only evidence can.

---

### STEP 7 — EVIDENCE ARRIVES, RE-SCREEN, RESOLVED 🟢 *(50 s)*

**What I say:**

> "Now the actual lab result lands in the record. I re-screen — and the
> obligation closes itself, because the thing it was waiting for exists."

**What I do:** run in Terminal 3:

```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/backend
python3 - <<'PY'
import json, urllib.request, copy
B = "http://127.0.0.1:8000"
patient = json.load(open("fixtures/patient_incomplete.json"))
trial   = json.load(open("fixtures/trial_demo.json"))
p = copy.deepcopy(patient)
p["labs"].append({"name":"eGFR","value":58,"unit":"mL/min","observed_at":"2026-09-07"})
req = urllib.request.Request(B + "/screen", method="POST",
        data=json.dumps({"patient": p, "trial": trial}).encode(),
        headers={"Content-Type": "application/json"})
res = json.load(urllib.request.urlopen(req))
inc4 = [c for c in res["criteria_results"] if c["criterion_id"] == "INC-04"][0]
print("INC-04 :", inc4["status"])
print("overall:", res["overall_status"])
PY
```

3. Back to the browser, reload the obligation.

**Audience sees:** status **RESOLVED**, and a line reading
`Resolved by SYSTEM: The detector no longer reports this requirement as
outstanding.` Ledger ends with `RESOLVED`.

**Expected result:** `INC-04: PASS`, `overall: REVIEW_REQUIRED`.

> **Say this out loud — it is a strength, not a bug:** the overall verdict
> stays REVIEW_REQUIRED because criterion **EXC-02 is still UNKNOWN** in this
> record. One criterion was satisfied; the system refuses to call the whole
> patient eligible on the strength of it. 🟢 Verified.

---

### STEP 8 — CLOSE *(20 s)*

**What I say:**

> "Detected, owned, chased, answered, closed — and every step of that is
> reconstructable from the ledger. Rules decide. AI assists. Humans approve."

---

## 8. How to present the AI (without it looking like a chatbot)

Say this during STEP 3, pointing at the provenance badge.

> "This isn't a chat box. The investigation is a bounded read-only agent.
> It's given six tools — the obligation, the ledger, the screening result, the
> criterion, the patient's labs, the patient's notes — and it can call those
> and nothing else. It returns one structured object: subject, body, reason,
> and an explicit list of what it *couldn't* determine. Every field is
> re-validated against a schema on our side. If the model returns malformed
> JSON, or a banned phrase, or names a recipient that doesn't exist in the
> registry, we throw the output away and fall back to a deterministic
> template. The badge tells you which one you're looking at."

**The facts behind that, all verified in code:**

| Question | Answer |
|---|---|
| What evidence does the model get? | Read-only via `TrialReadFacade` — `get_obligation`, `get_ledger`, `get_screening_result`, `get_criterion`, `get_patient_labs`, `get_patient_notes`. These six appear in `tools_called`. |
| What may it reason about? | How to phrase a request for missing evidence, and what it could not resolve. |
| Structured output | `InvestigationOutput`: `subject`, `body`, `reason`, `unresolved[]`. Enforced by JSON-schema-constrained generation *and* re-validated with Pydantic. |
| What it cannot do | Choose a recipient (registry does), alter protocol or eligibility truth, modify clinical data, approve, send, or change obligation state. |
| Validation | `validate_draft()` — banned phrases (`guarantee`, `definitely eligible`, `you must`, `diagnos`), body length ceiling, recipient must exist. |
| Failure path | Invalid → one repair attempt → deterministic template. `degraded: true` on provenance. |
| Where a human enters | `approve()` — reviewer and note both mandatory, enforced server-side (`REVIEWER_REQUIRED`). |

**The badge** renders `provider_kind`, `model_name`, a red `DEGRADED` flag,
and any `unresolved` items — so the UI never hides a fallback.

If you are on TemplateProvider, own it:

> "Right now this is running the deterministic provider, which is the floor the
> whole design is built on. The queue, the approval boundary, the ledger and
> the delivery all work identically whether a model answered or not — that's
> the point of the abstraction, and it's why a model outage can't take the
> workflow down."

---

## 9. Gmail inbound — 🔴 OPTIONAL / BACKUP ONLY

**Do not put this in the live demo.** Verified blockers:

1. `POST /comms/gmail/poll` hardcodes the query `is:unread label:trialguard`.
   The route calls `inbound.poll_gmail(ctx.repository, ctx.service)` with no
   override — **there is no way to change the query over HTTP.**
2. **The `trialguard` label does not exist** in the sender mailbox. Verified
   against the live Gmail API: user labels are
   `[Notion], Notes, Signal, Course, Admin, Noise`.
3. Matching requires the reply to land in the **same Gmail thread** as the sent
   proposal (`find_proposal_by_thread_id`).

Consequence: the poll will return `fetched: 0` every time, forever, until
someone creates the label and applies it. Verified live — it returned
`{"fetched": 0, "matched": 0, ...}` in 893 ms.

**Use `POST /obligations/{id}/responses` instead** (STEP 6). It is described in
the code itself as "the manual demo + test path", performs the *same*
`classify_response()` call, and writes the same `RESPONSE_RECEIVED` ledger
entry. The only thing it skips is the Gmail transport — which you already
demonstrated outbound in STEP 5.

**If a judge asks whether inbound works**, be precise:

> "Outbound is live — you saw the email. Inbound is implemented: polling,
> deterministic thread matching, idempotency on message id, and classification.
> What's not done is the mailbox plumbing — it filters on a Gmail label I
> haven't configured on this account. So I demo the classification path
> directly rather than claim a round-trip I haven't proven."

**To make it work later:** create a Gmail label named exactly `trialguard` on
`davidson4988@gmail.com`, add a filter applying it to replies, leave the reply
unread, then `curl -X POST http://127.0.0.1:8000/comms/gmail/poll`. 🟡 Not
verified end-to-end.

---

## 10. Resolution demo

Covered as STEP 7. The method chosen — a second `POST /screen` with the eGFR
appended — is the safest of the options, and here is why the others were
rejected:

| Method | Verdict |
|---|---|
| **API re-screen** | ✅ **Use this.** Runs the real detector and the real reconciliation path. No file edits, no DB surgery, repeatable. |
| UI | ❌ Not possible — no re-screen control exists anywhere in the frontend. |
| Fixture edit | ❌ Mid-demo file editing; and the Screening tab's sample is P-1042, not P-3311. |
| Direct DB update | ❌ Bypasses the detector — you would be faking the very thing you are demonstrating. |
| `POST /monitoring/demo/seed` | ❌ Wrong tool. It seeds the monitoring cohort from `patient_eligible` and creates no missing-lab obligation. |

Verified sequence 🟢: `OPEN` → evidence arrives → re-screen → `RESOLVED`,
resolution `SATISFIED`, by `SYSTEM`.

---

## 11. Population view — include only if you have spare time *(<30 s)*

**Navigation:** click the **Monitoring** tab in the top bar → the Trial
Overview is the top panel.

**What it shows:** `Patients`, `Active treatments`, `Need attention`,
`Unassessable`, and an all-patients table.

**The one insight to mention:**

> "'Unassessable' is separate from 'needs attention' on purpose — a patient we
> couldn't assess is a data-quality problem, not a clinical one, and merging
> those two numbers is how real trials lose track of people."

⚠️ **Accuracy warning:** the backend *does* add an `obligations` aggregate to
`GET /monitoring/trials/{id}/overview`, but `TrialOverview.tsx` **never renders
it**. Do not promise an obligations dashboard — it exists in the API only (🟡).
If the Monitoring tab is empty, you have not seeded the cohort; skip this
section entirely rather than seeding live.

---

## 12. Backup plans

Every fallback below is real system behaviour, verified. None of them requires
you to pretend.

### PATH A — Full live demo

Everything in §7. Requires: Postgres healthy, backend on 8000, frontend on
5173, Gmail `SET`, `/health` clean.

### PATH B — Local AI unavailable 🟢 verified

**Notice:** provenance badge reads `TEMPLATE`, or shows a red `DEGRADED`;
`curl …:11434/api/tags` gives `HTTP=000`.

**Do:** nothing. The workflow is unaffected. If you had `MODEL_PROVIDER=local`
set, unset it and restart (~1 s) to avoid a per-request probe delay.

**Say:**

> "Normally this investigation is drafted by our local Qwen model over an SSH
> tunnel to my PC. The tunnel isn't up, so the architecture has degraded to the
> deterministic TemplateProvider — which is exactly the designed behaviour. The
> queue, the approval boundary, the ledger and the delivery are untouched. The
> badge is telling you the truth about which provider answered."

**Still demonstrable:** everything. All eight steps.

### PATH C — Gmail unavailable, or a WhatsApp misclick 🟢 verified

**Notice:** `Proposal PA-…: FAILED via … — FAILED: <error>`, and the ledger
shows `DELIVERY_FAILED` instead of `MESSAGE_SENT`.

**Do:** this is recoverable *live*. Verified: on delivery failure the proposal
is marked `FAILED`, the ledger records `DELIVERY_FAILED`, and **the obligation
stays OPEN**. Click **"Draft a request"** again — you get a fresh DRAFT on
EMAIL — and approve again.

**Say:**

> "The send failed, and look at what the system did with that: it did *not*
> mark the obligation as handled. It recorded the failure in the ledger, left
> the obligation open, and let me retry. A follow-up system that loses track of
> a failed follow-up is worse than no system at all."

**Still demonstrable:** detection, queue, investigation, provenance, approval,
ledger, failure handling, response classification, resolution. Only the inbox
screenshot is lost.

### PATH D — Database or API problem 🟢 verified

**Notice:** `/health` shows `persistence_degraded: true` or
`persistence_backend: "json"`; or the UI banner reads `NETWORK_ERROR`.

**Do:** first check the backend is on **port 8000** — a wrong port is the most
likely cause and the fix is one restart. If Postgres itself is down, run the
JSON rollback:

```bash
# Terminal 1: Ctrl-C
unset DATABASE_URL
export PERSISTENCE=json
python -m uvicorn app.main:app --port 8000
```

Then re-seed with §5.4. The entire loop works on JSON — verified end-to-end
(OPEN → approve → SENT → re-screen → RESOLVED).

**Say:**

> "Persistence is behind a repository interface. Postgres gives us real
> constraints, but there's a JSON-file rollback that runs the identical code
> paths, and the app degrades to it rather than refusing to start."

### PATH E — Frontend problem

**Notice:** Vite fails, or the page is blank/erroring.

**Do:** drive the same demo from `http://127.0.0.1:8000/docs` (FastAPI's
interactive Swagger UI), in this order:
`POST /screen` → `GET /obligations/queue` → `GET /obligations/{id}` →
`GET /obligations/{id}/actions` → `POST /obligations/{id}/investigate` →
`POST /obligations/proposals/{id}/approve` → `POST /screen` again.

**Say:**

> "The UI is a client of the same API — let me show you the contract directly."

Honestly, the ledger JSON is compelling on its own. Do not apologise for this.

---

## 13. Things I must NOT do during the demo

Each of these is grounded in verified behaviour of this repository.

1. **Do not run `pytest`.** 🟢 It drops the `trialguard` schema and wipes your
   demo data (§0.2). This is the single most destructive thing you could type.
2. **Do not open or `cat` `.env.local`**, and do not screen-share a terminal
   where it might scroll past. Use the SET/MISSING check in §3.E.
3. **Do not print the Gmail refresh token, client secret, or `META_ACCESS_TOKEN`.**
4. **Do not touch the channel dropdown.** Selecting WhatsApp fails with
   `RECIPIENT_PHONE_MISSING` and consumes the DRAFT proposal (§0.5).
5. **Do not attempt a WhatsApp live send.** 🔴 Meta reports the number as
   `ON_PREMISE` (the code targets Cloud API), `NOT_VERIFIED`, with **zero**
   approved templates. It cannot succeed.
6. **Do not rely on Gemini.** 🔴 Free-tier quota is exhausted — a hosted
   investigation costs ~21 s and then degrades anyway. Leave `MODEL_PROVIDER`
   unset.
7. **Do not click "Approve & send" more than once** per obligation. The second
   attempt returns `PROPOSAL_NOT_DRAFT` — correct behaviour, awkward on stage.
8. **Do not run the backend with `--reload`.** A stray save restarts it.
9. **Do not re-seed repeatedly.** Screening the same patient again is
   deduplicated (good), but extra patient ids clutter the queue.
10. **Do not change configuration in the last 15 minutes.** No new env vars, no
    provider switches, no `npm install`.
11. **Do not run `alembic downgrade` unless you intend to reset** — and never
    while the backend is running.
12. **Do not claim inbound Gmail is live.** It is not (§9).

---

## 14. Rehearsal timeline

### T-60 — full dress rehearsal

```bash
docker compose up -d postgres
cd backend && source .venv/bin/activate
export PERSISTENCE=postgres
export DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard"
export MIGRATION_DATABASE_URL="$DATABASE_URL"
python -m alembic upgrade head && python -m alembic current
```

- [ ] `alembic current` → `4caba4bb846e (head)`
- [ ] Start backend (Terminal 1), frontend (Terminal 2)
- [ ] `/health` shows postgres / not degraded / obligations enabled / EMAIL gmail
- [ ] Seed (§5.4) → queue `total: 1`
- [ ] **Walk all 8 steps of §7, including one real approve.** This is the only
      rehearsal email you should send.
- [ ] Confirm it arrived in tab 2
- [ ] Reset (§5.5) and re-seed

### T-30 — tunnel and decision

- [ ] `curl -s -m 5 -o /dev/null -w "HTTP=%{http_code}\n" http://127.0.0.1:11434/api/tags`
- [ ] If `HTTP=200`: `curl -s …/api/tags | grep qwen3.5:9b`
- [ ] **Decide now: local model or TemplateProvider.** Do not revisit this.
- [ ] If unsure → TemplateProvider. Path B language is ready.

### T-15 — final state

- [ ] Backend running on **8000**, no `--reload`
- [ ] Frontend on **5173**
- [ ] `/health` clean
- [ ] Demo data seeded → `{'total': 1, 'needs_decision': 0, 'awaiting_response': 0}`
- [ ] Obligation detail opens; ledger shows `#1 DETECTED` **and no proposal yet**
- [ ] Gmail creds: four `SET` lines
- [ ] Recipient check → `SITE-03  maste005kar2005@gmail.com`
- [ ] **Do not investigate.** A pending DRAFT makes STEP 3 fail with
      `PROPOSAL_PENDING`.

### T-5 — presentation state

- [ ] Browser tab 1: `localhost:5173`, **Work Queue** tab selected, queue visible
- [ ] Browser tab 2: coordinator inbox, loaded, scrolled to top
- [ ] Terminal 3 open with the STEP 6 and STEP 7 commands **already typed, not run**
- [ ] Notifications silenced, `.env.local` not open in any editor
- [ ] Terminals 1 and 2 minimised
- [ ] Water. Breathe.

---

## 15. Speaking script

**Opening — 20 s**

> "Hi — I'm building TrialGuard. Clinical trials don't usually fail because
> someone made a wrong decision. They fail because something was missing and
> nobody chased it down."

**Problem — 30 s**

> "A coordinator screens a patient, one lab result hasn't come back, and that
> patient sits in limbo. Most systems either guess, or mark the patient
> ineligible, or drop the gap into a spreadsheet nobody owns. All three are
> bad. Missing data is not a verdict — it's a task, and it needs an owner."

**Demo — 3–5 min**

Follow §7. Keep talking through the two terminal commands so the pace never
drops.

**Architecture — 45 s**

> "Three layers. Deterministic rules decide eligibility — a model never touches
> a verdict. The agent layer drafts communication: read-only tools, structured
> output, schema-validated, and it falls back to a deterministic template if
> anything is off. Then a human approves, by name, with a note, before anything
> leaves the system. Persistence is Postgres, with the 'one open obligation per
> requirement' rule enforced as a database constraint rather than application
> code I have to remember to write correctly."

**Business value — 30 s**

> "A coordinator running three trials has maybe forty of these open at once.
> Today that's a spreadsheet and a memory. Here, every one has an owner, an
> audit trail and a resolution condition — and when the evidence arrives, it
> closes itself. That's fewer screen failures and a shorter time to enrolment."

**Closing — 15 s**

> "Rules decide, AI assists, humans approve — and the ledger means you can
> reconstruct exactly what happened and who decided it. Happy to take
> questions."

---

## 16. Judge Q&A hooks

**On the AI — "Why AI at all? This looks like a template."**
> Because the drafting is the only part that genuinely varies, and it's also
> the only part where being wrong is cheap — a human reads it before it sends;
> the template floor exists so the workflow survives the model being down.

**"Isn't the model just a text generator here?"**
> Deliberately, yes — it gets six read-only tools and returns one validated
> structured object, because letting it touch eligibility would put an
> unauditable component in a regulated decision.

**On `ai_provider: mock-slm-v1` — "So it's fake?"**
> That field is the Phase-2 risk provider, which is a separate pluggable slot
> with a real trained Isolation Forest behind `RISK_PROVIDER=synthetic_ml`; the
> agent's provenance badge is what reports the drafting model.

**On PostgreSQL — "How does this scale?"**
> The hot query is the queue, which is a single indexed read on
> `(trial_id, status, priority, first_detected_at)`, and obligation identity is
> a partial unique index — so correctness holds under concurrency rather than
> depending on application-level locking.

**On Gmail — "Can this integrate with other systems?"**
> Delivery is an interface — Gmail, WhatsApp and in-app all implement it and
> the obligation engine can't tell which answered; a Slack or Teams provider is
> one class.

**On human approval — "Why not automate it completely?"**
> Because the failure mode of a wrong automated message to a trial site is a
> protocol deviation, and the approval costs about four seconds.

**On fallback — "What if the model or API goes down?"**
> Every provider degrades instead of failing: the model falls back to the
> deterministic template in 0.12 seconds, email falls back to in-app, and
> Postgres falls back to a JSON store — and each degradation is visible on
> `/health` or the provenance badge rather than silent.

**On WhatsApp — "You mentioned WhatsApp, does it work?"**
> The provider is built and tested for both template and session mode, but the
> number is registered on Meta's On-Premise API rather than Cloud API and has
> no approved templates, so I'm not going to claim a live send I can't make.

**On inbound — "Does it read replies?"**
> Outbound is live; inbound polling, thread matching and classification are
> implemented and unit-tested, but the mailbox label plumbing isn't configured,
> so I demo the classification path directly.

**On data — "Is this real patient data?"**
> No — synthetic fixtures, and the recipient is my own mailbox.

**"What would you build next?"**
> Escalation on a timer — the obligation already carries `escalation_count` and
> a due date, so the next step is a scheduled re-send to the next responsible
> party up the chain.

---

## 17. One-page cheat sheet

```
╔══════════════════════════════════════════════════════════════════════╗
║ STARTUP                                                              ║
╚══════════════════════════════════════════════════════════════════════╝
 docker compose up -d postgres

 T1: cd backend && source .venv/bin/activate
     export PERSISTENCE=postgres
     export DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard"
     python -m uvicorn app.main:app --port 8000        # MUST be 8000

 T2: cd frontend && npm run dev                        # 5173

╔══════════════════════════════════════════════════════════════════════╗
║ HEALTH                                                               ║
╚══════════════════════════════════════════════════════════════════════╝
 curl -s http://127.0.0.1:8000/health | python3 -m json.tool
   persistence_backend  = postgres
   persistence_degraded = false
   obligations_enabled  = true
   EMAIL                = gmail

 SEED (after backend is up):  see §5.4
   → {'total': 1, 'needs_decision': 0, 'awaiting_response': 0}
 RECIPIENT: curl -s http://127.0.0.1:8000/obligations/parties
            → SITE-03  maste005kar2005@gmail.com

╔══════════════════════════════════════════════════════════════════════╗
║ DEMO                                        EXPECTED                 ║
╚══════════════════════════════════════════════════════════════════════╝
 1 Work Queue tab                             1 row, P-3311, OPEN
 2 Click the row                              EVIDENCE + ledger #1 DETECTED
 3 "Draft a request"                          DRAFT, badge=TEMPLATE, Email
 4 Reviewer "Dr. Rao" + note → Approve & send EXECUTED via gmail — SENT
 5 Browser tab 2                              the real email
 6 Terminal: POST /responses                  classified: PROVIDED (0.7)
 7 Terminal: re-screen with eGFR 58           INC-04 PASS → RESOLVED
 8 Close                                      ledger ends RESOLVED

 ⚠ NEVER: touch the channel dropdown · run pytest · approve twice
          open .env.local · use --reload

╔══════════════════════════════════════════════════════════════════════╗
║ BACKUP                                                               ║
╚══════════════════════════════════════════════════════════════════════╝
 Ollama down  → nothing to do. Badge says TEMPLATE/DEGRADED. §12-B
 Send FAILED  → obligation stays OPEN. Click "Draft a request" again. §12-C
 DB down      → unset DATABASE_URL; PERSISTENCE=json; restart; re-seed. §12-D
 UI down      → drive it from http://127.0.0.1:8000/docs. §12-E
 Blank queue  → you were wiped by pytest, or not seeded. Re-run §5.4.
 NETWORK_ERROR→ backend is not on port 8000.
 Errno 48     → something already owns 8000:  lsof -nP -iTCP:8000 -sTCP:LISTEN
 backend=json → env didn't reach uvicorn. Use: env PERSISTENCE=postgres \
                DATABASE_URL=... .venv/bin/python -m uvicorn app.main:app --port 8000
```

---

**Final word.** The strongest thing about this demo is not the AI — it's that
every failure mode you might hit on stage is one the system already handles
honestly, and you can narrate it as a design decision because it is one.
