# TrialGuard — 2-Minute Video Demo Script

Every click, label, endpoint and expected screen below was verified against the
running application on 2026-09-07. Where the product does **not** do something,
this document says so rather than scripting around it.

**Target runtime: 1:56.** Narration is ~220 spoken words (~90 s at presentation
pace), leaving deliberate pauses. Do not add sentences — the timing has no slack.

**Verified environment for this script**

| Component | State | Consequence for the script |
|---|---|---|
| PostgreSQL (docker, port 5433) | running, healthy | persistence is real |
| Backend on **port 8000** | required — `vite.config.ts` hardcodes the proxy | any other port ⇒ whole UI shows `NETWORK_ERROR` |
| Gmail outbound | **live verified** (real message ID, delivered) | the send in this video is real |
| TemplateProvider | **live verified**, instant (0 ms) | the deterministic path, always available |
| Local Qwen3.5:9B via Ollama | **not currently reachable** — SSH tunnel to `maste@192.168.29.115` is listening on 11434, but the PC side does not answer | Path A below is *conditional*; Path B is the default |
| Hosted Gemini | free-tier quota exhausted | do not use in the video |

---

## THE 2-MINUTE SCRIPT

### 0. OPENING HOOK — 00:00–00:08

**SCREEN** Browser fullscreen, `http://localhost:5173`, **Monitoring** tab already
selected, scrolled to top. Nothing else on screen.

**WHAT I DO** Nothing. Hold on the Trial overview for the first two seconds.

**WHAT THE VIEWER SEES** `CT-001`, four metrics — `Patients 6`, `Active
treatments 6`, `Need attention 3` (red, with a dot), `Unassessable 1` — and
below them the Trial operations overview panel with the donut.

**WHAT I SAY**
> "A trial doesn't stall because nobody spotted a missing lab. It stalls because nobody owned chasing it."

**EXPECTED RESULT** Static, composed opening frame. No interaction.

---

### 1. TRIAL-LEVEL MONITORING — 00:08–00:22

**SCREEN** Same page.

**WHAT I DO** Move the cursor across, in this order: the donut → the `Open work`
column → the `Patient status map` tiles. Do not click. Do not scroll past the
status map.

**WHAT THE VIEWER SEES**
- Donut: `6 PATIENTS` in the centre; legend `RED 2 · 33%`, `UNKNOWN 1 · 17%`,
  `AMBER 0 · 0%`, `GREEN 3 · 50%`
- `Open work`: `1` — "obligation needs action · mostly open"
- `Outstanding work by patient`: a single bar, `P-3311`, `1 open`
- `Patient status map`: `P-2003 Hold`, `P-2004 Hold` (red tiles), `P-2006 Review
  required` (dashed, unknown), `P-2001 / P-2002 / P-2005 Proceed` (green)

**WHAT I SAY**
> "This is CT-001. Six patients, three need attention, one open piece of work. TrialGuard scores the whole population, and it separates a clinical problem from a data-quality one."

**EXPECTED RESULT** Judge grasps the population state without reading small text.

> **Accuracy note for the operator:** `Unassessable 1` is P-2006 — the
> data-quality gate overrode the model. That is a *data* problem, not a safety
> signal. Don't call it "a sick patient".

---

### 2. THE PATIENT CARRYING THE WORK — 00:22–00:32

**SCREEN** Same page.

**WHAT I DO** Point at the `Outstanding work by patient` bar (`P-3311`). Then
click **Work Queue** in the top navigation.

> **Do not click the P-3311 bar itself.** It navigates to that patient's
> monitoring view, not to the obligation. Verified.

**WHAT THE VIEWER SEES** Work Queue list: `Work Queue`, `Trial CT-001 · 1 open ·
0 awaiting your decision · 0 awaiting a response`, and one row — a `LOW` badge,
`Evidence required by INC-04 is not on file`, `P-3311 · MISSING_LAB_EVIDENCE ·
OPEN · Site 03 — Coordinator`.

**WHAT I SAY**
> "One patient is carrying that open work — P-3311. Screening couldn't evaluate inclusion criterion four, because there's no eGFR result on file."

**EXPECTED RESULT** Queue list on screen. Move through it fast — it is one row
in a lot of whitespace; do not linger.

---

### 3. THE OBLIGATION — 00:32–00:47

**SCREEN** Work Queue.

**WHAT I DO** Click the row `Evidence required by INC-04 is not on file`.

**WHAT THE VIEWER SEES** The obligation detail, all in one viewport, no
scrolling:
- Title + `OPEN`
- `Patient P-3311` · `Requirement INC-04 (CT-001)` · `Priority LOW` ·
  `Escalations 0`
- `EVIDENCE` — `INC-04: eGFR >= 45 mL/min — No eGFR result available for this patient`
- `FOLLOW-UP LEDGER` — `#1 DETECTED — … · SYSTEM`
- `PROPOSED ACTION` with a **Draft a request** button

**WHAT I SAY**
> "Most systems record that as 'unknown' and move on. TrialGuard turns it into an obligation — an owner, a priority, the evidence behind it, and a ledger that starts the moment it's detected."

**EXPECTED RESULT** The obligation reads as owned, trackable work.

---

### 4. INVESTIGATION — 00:47–01:00

**SCREEN** Obligation detail.

**WHAT I DO** Click **Draft a request**.

**WHAT THE VIEWER SEES** The `PROPOSED ACTION` panel fills in, instantly:
a provenance badge, `Channel: Email`, `RECIPIENT — Site 03 — Coordinator` with
the address, and the drafted subject and body:

```
CT-001 / P-3311 — Evidence required by INC-04 is not on file

Screening for P-3311 against CT-001 cannot complete because requirement
INC-04 (eGFR at least 45 mL/min) has no result on file.

Relevant record note: eGFR >= 45 mL/min

Could you confirm whether the result is available and provide it?
```

Choose the narration that matches the badge actually on screen:

**Path B — badge reads `TEMPLATE`** *(default; this is the current verified state)*
> "I ask it to draft the follow-up. This is the deterministic floor the whole design sits on — the same tools, the same structured output, no model in the loop."

**Path A — badge reads `LOCAL` + `qwen3.5:9b`** *(only if §Pre-demo step 5 confirmed it live)*
> "I ask it to draft the follow-up. A read-only agent pulls the obligation, the criterion and the patient's labs, and returns a structured proposal — subject, body, and anything it couldn't resolve."

**EXPECTED RESULT** Draft visible in under a second on Path B. On Path A expect
a few seconds — keep talking through it.

> **Never call the TEMPLATE badge "AI".** The badge is on screen; the narration
> must match it.

---

### 5. HUMAN APPROVAL — 01:00–01:10

**SCREEN** Obligation detail.

**WHAT I DO** Type `Dr. Rao` into **Reviewer**. Type `Reviewed and accurate.`
into **Note (required)**. Do not touch the **Channel** dropdown — it is already
`Email`.

**WHAT THE VIEWER SEES** The **Approve & send** button enabling as the fields
fill.

**WHAT I SAY**
> "Rules decide. AI assists. Humans approve. Nothing leaves this system without a named reviewer and a note — the API rejects it otherwise."

**EXPECTED RESULT** Both fields filled, button live.

> **Landmine:** selecting `WhatsApp` in the dropdown fails with
> `RECIPIENT_PHONE_MISSING` and consumes the draft. Never touch it on camera.

---

### 6. REAL GMAIL SEND — 01:10–01:25

**SCREEN** Obligation detail → then browser tab 2.

**WHAT I DO** Click **Approve & send**. Wait ~1.5 s. Then switch to the
pre-opened Gmail tab and point at the newest message.

**WHAT THE VIEWER SEES**
`Proposal PA-…: EXECUTED via gmail (EMAIL) — SENT`, then the real email in the
inbox, subject `CT-001 / P-3311 — Evidence required by INC-04 is not on file`.

**WHAT I SAY**
> "Approved — and that's the real Gmail API, with a provider message ID. Gmail is one implementation behind a delivery interface; WhatsApp and in-app sit behind the same one."

**EXPECTED RESULT** One real email. Send exactly once.

---

### 7. LEDGER — 01:25–01:35

**SCREEN** Switch back to the browser tab with the obligation.

**WHAT I DO** Point at the `FOLLOW-UP LEDGER` block.

**WHAT THE VIEWER SEES** Four entries:
`#1 DETECTED` · `#2 PROPOSAL_CREATED` · `#3 MESSAGE_SENT` · `#4 PROPOSAL_APPROVED`
— each with a timestamp and actor, and the obligation now `AWAITING_RESPONSE`.

**WHAT I SAY**
> "The ledger carries the whole chain: detected, drafted, sent, approved. That's an audit trail, not a sent-items folder."

**EXPECTED RESULT** The history reads as reconstructable.

---

### 8. RESOLUTION — 01:35–01:50

**SCREEN** Small terminal window (pre-positioned, command already typed, **not**
yet run) → then back to the browser.

**WHAT I DO** Press Enter on the pre-typed command. Switch to the browser, click
**← Back to queue**, then click the row again.

The command (already typed before recording starts):

```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/backend && python3 - <<'PY'
import json, urllib.request, copy
B = "http://127.0.0.1:8000"
patient = json.load(open("fixtures/patient_incomplete.json"))
trial   = json.load(open("fixtures/trial_demo.json"))
p = copy.deepcopy(patient)
p["labs"].append({"name": "eGFR", "value": 58, "unit": "mL/min", "observed_at": "2026-09-07"})
req = urllib.request.Request(B + "/screen", method="POST",
        data=json.dumps({"patient": p, "trial": trial}).encode(),
        headers={"Content-Type": "application/json"})
res = json.load(urllib.request.urlopen(req))
print("INC-04:", [c for c in res["criteria_results"] if c["criterion_id"] == "INC-04"][0]["status"])
PY
```

**WHAT THE VIEWER SEES** Terminal prints `INC-04: PASS`. In the browser the
obligation now reads `RESOLVED`, with
`Resolved by SYSTEM: The detector no longer reports this requirement as
outstanding.` and `#5 RESOLVED` in the ledger.

**WHAT I SAY**
> "The lab result lands in the record. We re-screen — the criterion flips to pass, and the obligation closes itself. Resolved by the system, not by someone remembering to tick it off."

**EXPECTED RESULT** `RESOLVED`. This is the payoff — hold it for two seconds.

> **Do not say the patient is now eligible.** The overall verdict stays
> `REVIEW_REQUIRED` because criterion EXC-02 is still unknown. One criterion was
> satisfied; the system correctly refuses to over-conclude. If a judge asks,
> that's the honest answer and it's a strength.

---

### 9. CLOSE — 01:50–01:56

**SCREEN** Click **Monitoring** in the top nav. Land on the Trial overview.

**WHAT I SAY**
> "Detected, owned, chased, and verifiably closed. That's the loop TrialGuard runs."

**EXPECTED RESULT** End on the strongest frame. Cut.

---

## PRE-DEMO SETUP

Complete every step **before** recording. Steps 1–4 and 8 are required; 5 is
optional and decides which narration you use in §4.

**1. PostgreSQL**
```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant
docker compose up -d postgres
docker ps --format "{{.Names}} {{.Status}}" | grep postgres     # expect: Up … (healthy)
```

**2. Migrations + clean slate**
```bash
cd backend && source .venv/bin/activate
export DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard"
export MIGRATION_DATABASE_URL="$DATABASE_URL"
python -m alembic downgrade base && python -m alembic upgrade head
python -m alembic current      # expect: 4caba4bb846e (head)
```

**3. Backend — must be port 8000**
```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/backend
lsof -nP -iTCP:8000 -sTCP:LISTEN        # expect NO output; kill anything listed
env PERSISTENCE=postgres \
    DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard" \
    .venv/bin/python -m uvicorn app.main:app --port 8000
```
No `--reload` — a stray file save restarts it mid-take.

**4. Frontend**
```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/frontend && npm run dev
```

**5. SSH tunnel + Ollama — optional, decides §4 Path A vs B**

The tunnel command (your existing host):
```bash
ssh -N -L 11434:127.0.0.1:11434 maste@192.168.29.115
```
On the PC: `ollama serve`, then `ollama list` and confirm `qwen3.5:9b`.

Then, on the Mac, the only check that matters:
```bash
curl -s -m 5 -o /dev/null -w "HTTP=%{http_code}\n" http://127.0.0.1:11434/api/tags
```
- `HTTP=200` → restart the backend from step 3 with `MODEL_PROVIDER=local`
  prepended, and use **Path A** narration.
- `HTTP=000` → leave `MODEL_PROVIDER` unset and use **Path B**. *(This was the
  state at the time of writing: the tunnel was listening, but the PC side did
  not answer.)*

**6. Gmail — verify without printing secrets**
```bash
cd backend && source .venv/bin/activate
python -c "
from dotenv import dotenv_values
v=dotenv_values('../.env.local')
for k in ('GMAIL_CLIENT_ID','GMAIL_CLIENT_SECRET','GMAIL_REFRESH_TOKEN','GMAIL_SENDER'):
    print(f'{k:22}', 'SET' if (v.get(k) or '').strip() else 'MISSING')"
```
Expect four `SET` lines. This prints no values.

**7. Health check**
```bash
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```
Require: `"persistence_backend": "postgres"`, `"persistence_degraded": false`,
`"obligations_enabled": true`, `"EMAIL": "gmail"`.

**8. Demo data — the exact recording state**
```bash
cd ~/Projects/Clinical-Trial-Matching---Research-Assistant/backend
python3 - <<'PY'
import json, urllib.request
B = "http://127.0.0.1:8000"
urllib.request.urlopen(urllib.request.Request(B + "/monitoring/demo/seed", method="POST",
    data=json.dumps({"trial_id": "CT-001"}).encode(), headers={"Content-Type": "application/json"}))
pa = json.load(open("fixtures/patient_incomplete.json")); tr = json.load(open("fixtures/trial_demo.json"))
urllib.request.urlopen(urllib.request.Request(B + "/screen", method="POST",
    data=json.dumps({"patient": pa, "trial": tr}).encode(), headers={"Content-Type": "application/json"}))
q  = json.load(urllib.request.urlopen(B + "/obligations/queue?trial_id=CT-001"))
ov = json.load(urllib.request.urlopen(B + "/monitoring/trials/CT-001/overview"))
pr = json.load(urllib.request.urlopen(B + "/obligations/proposals"))
print("queue    :", q["counts"])
print("risk     :", ov["risk_counts"], "patients:", ov["total_patients"])
print("proposals:", len(pr), "(must be 0)")
PY
```
Required output — if it differs, re-run step 2 then step 8:
```
queue    : {'total': 1, 'needs_decision': 0, 'awaiting_response': 0}
risk     : {'GREEN': 3, 'AMBER': 0, 'RED': 2, 'UNKNOWN': 1} patients: 6
proposals: 0 (must be 0)
```

**9. Browser tabs**

| Tab | URL | State before recording |
|---|---|---|
| 1 | `http://localhost:5173` | **Monitoring** tab selected, scrolled to top |
| 2 | `https://mail.google.com` | signed in as the recipient, inbox open, scrolled to top |

Terminal window: small, positioned bottom-right or on a second display, with the
§8 resolution command **typed but not run**.

**Do not click "Draft a request" during setup.** A pending draft makes §4 fail
with `PROPOSAL_PENDING`. If you rehearse the full flow, re-run steps 2 and 8.

---

## BACKUP PATH — Local model unavailable

This is the default, not a degraded mode: the deterministic provider is the
verified path and produces the identical proposal, instantly.

**Switch:** leave `MODEL_PROVIDER` unset (or `unset MODEL_PROVIDER` and restart
the backend from setup step 3). Restart takes about a second.

**Use Path B narration in §4.** Everything else in the script — timings, clicks,
screens, the Gmail send, the ledger, the resolution — is unchanged, because the
approval boundary and delivery layer do not care which provider drafted.

If a judge asks why it isn't the model:
> "The local model runs on my PC over an SSH tunnel and it isn't up right now. The architecture degrades to the deterministic provider — that's the designed behaviour, and the badge on screen tells you which one answered rather than hiding it."

---

## FAILURE HANDLING

| Problem | What I do | What I say |
|---|---|---|
| Ollama unreachable | Nothing. Badge reads `TEMPLATE`; use Path B narration | "The architecture degrades to the deterministic provider — the badge tells you which one answered." |
| Gmail send fails | Keep going. Proposal shows `FAILED`, ledger shows `DELIVERY_FAILED`, obligation stays `OPEN`. Click **Draft a request** again and re-approve | "The send failed — and the system didn't mark the obligation as handled. It logged the failure and left the work open." |
| Draft doesn't appear / `PROPOSAL_PENDING` | A draft already exists from a rehearsal. Re-run setup steps 2 and 8 | *(cut and re-record)* |
| UI shows `NETWORK_ERROR` | Backend isn't on port 8000. Restart from setup step 3 | *(cut)* |
| `/health` shows `"json"` or `degraded: true` | Env vars didn't reach uvicorn. Use the `env VAR=… uvicorn` form in step 3 | *(cut)* |
| Queue empty / wrong counts | Re-run setup steps 2 then 8 | *(cut)* |
| Accidentally selected WhatsApp | Proposal goes `FAILED` with `RECIPIENT_PHONE_MISSING`, obligation stays `OPEN`. Click **Draft a request** again, leave channel on `Email` | "That channel has no number on file for this party, so it refused to send and kept the obligation open." |
| Browser refreshed mid-demo | Re-click **Work Queue**, re-open the row. No state is lost — it's all server-side | "All of this is persisted, so the view rebuilds from the database." |

---

## REHEARSAL CHEAT SHEET

```
00:00  Monitoring, hold        "…stalls because nobody owned chasing it."
00:08  Sweep donut → open work → status map
00:22  Point P-3311 bar → click Work Queue tab
00:32  Click the INC-04 row    obligation · evidence · ledger #1
00:47  Click "Draft a request" proposal + provenance badge
01:00  Type Dr. Rao + note     "Rules decide. AI assists. Humans approve."
01:10  Click "Approve & send"  EXECUTED via gmail — SENT
01:18  Switch to Gmail tab     the real email
01:25  Back to obligation      ledger #1–#4
01:35  Terminal: Enter         INC-04: PASS
01:42  Back to queue → row     RESOLVED
01:50  Click Monitoring        closing line
01:56  Cut
```

**Never on camera:** the Channel dropdown · `.env.local` · a second
`Approve & send` · `pytest` (it drops the demo schema).

---

## RECORDING STRATEGY

**Display and framing**
- Record at **1440×900**. The whole obligation detail fits in one viewport at
  this size — verified — so §3–§7 need **zero scrolling**.
- Browser zoom **100%**. The redesigned metrics and donut are already sized for
  projector legibility; zooming in crops the operations panel.
- Browser fullscreen (hide bookmarks bar). Hide desktop clutter and notifications.

**Windows**
- The terminal appears **once**, for §8, and should be small and off to one
  side. It earns its place there — "the lab result arrives" is more credible as
  a real API call than as a mimed click. Everywhere else, browser only.
- Pre-open both browser tabs. Never open a tab on camera.

**Scrolling**
- The Monitoring page is taller than the viewport. In §1 stop at the
  `Patient status map`; do not scroll into `Requiring attention` / `All
  patients` — they repeat information you have already shown and cost you 10 s.

**Where to pause**
- Two seconds on the opening frame before speaking.
- Two seconds on `RESOLVED` before the closing line. That is the payoff shot.

**Where to cut if editing**
- Between §6 and §7 (the browser tab switch to Gmail and back).
- Between §8's terminal command and the browser returning.
- Trimming those two gets a 1:56 take to roughly 1:45.

**Privacy**
- The recipient address `maste005kar2005@gmail.com` is visible on the proposal
  panel and in the Gmail tab. If the video will be public, either accept that or
  blur it in post — it is your own address, but it is a real one on screen.

**Title card**
- Optional, and only if it is ≤ 3 s and outside the 2:00 budget: `TrialGuard —
  clinical trial operations`. The opening frame is strong enough without one.

**Takes**
- Rehearse the full flow once, then **re-run setup steps 2 and 8** before the
  real take. A rehearsal leaves a draft proposal and a sent email behind.
