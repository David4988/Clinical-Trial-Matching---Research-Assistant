# Deployment

TrialGuard AI is deployed as two services.

```
Vercel                          Render
static Vite build   ──HTTPS──▶  FastAPI (uvicorn)
                                      │
                          ┌───────────┴────────────┐
                          │                         │
                   PERSISTENCE=postgres      PERSISTENCE=json (rollback)
                          │                         │
                     Supabase / any            persistent disk
                     PostgreSQL 15+                 │
                                          /var/data/store.json
                                          /var/data/monitoring.json
```

The backend is **not** serverless, and deliberately so — a single demo walks a
dozen requests that must all see each other's writes, and a serverless
function's ephemeral filesystem cannot guarantee that for the JSON fallback.

**Persistence is PostgreSQL by default** (`docs/FINAL_IMPLEMENTATION_PLAN.md`
§9–§11): set `DATABASE_URL` and the app runs on Postgres, with real
constraints, transactions and indexed queries. **Leave it unset and the app
runs on the original JSON-file store** — no code path changes, and this is a
live rollback, not a documented-but-unbuilt option: `repository/factory.py`
never raises, and an unreachable database degrades to JSON with a logged
warning rather than refusing to start. `GET /health` reports which backend is
actually live.

Nothing else about the application's behaviour changes between local and
production: same code paths, same risk provider. What's configurable: where
the API is, which browser origin may call it, which persistence backend is
live, and (only for the JSON fallback) where the JSON lives.

## Local PostgreSQL

`docker-compose.yml` at the repository root defines a throwaway Postgres 16 on
`127.0.0.1:5433`:

```
docker compose up -d postgres
cd backend
export DATABASE_URL="postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

`alembic upgrade head` creates the `trialguard` schema and every table — see
`docs/FINAL_IMPLEMENTATION_PLAN.md` §9.4 for the schema itself and §10.5 for
why `MIGRATION_DATABASE_URL` (defaulting to `DATABASE_URL`) and a plain
`search_path` matter for Alembic specifically. Switching a developer's demo
data over from an existing JSON store: `python scripts/import_json_store.py`
(after migrating).

Unset `DATABASE_URL` and the app boots on the JSON store exactly as before —
this is what the default `pytest tests -q` run does, and it needs no Docker at
all. The database-backed tests (`test_migrations.py`,
`test_repository_parity.py`, one case in `test_repository_factory.py`) skip
themselves, rather than fail, when Postgres is not reachable.

## Environment variables

Names only. Do not commit values.

### Vercel (frontend, build time)

| Variable | Required | Purpose |
| --- | --- | --- |
| `VITE_API_BASE_URL` | yes | Origin of the Render service, e.g. `https://trialguard-api.onrender.com`. Compiled into the browser bundle, so it must never hold a secret. |

Unset locally: the client falls back to `/api` and Vite's dev proxy forwards to
`127.0.0.1:8000`, so no `.env` file is needed to develop.

### Render (backend, runtime)

| Variable | Required | Value |
| --- | --- | --- |
| `RISK_PROVIDER` | yes | `synthetic_ml` — live Isolation Forest inference. Omitting it silently falls back to the deterministic mock. |
| `DATABASE_URL` | recommended | The Supabase (or any PostgreSQL 15+) connection string. See "Supabase" below. Omit it and the service runs on the JSON-file rollback instead — a real, tested fallback, not a missing feature. |
| `DB_SCHEMA` | no | Defaults to `trialguard`. Never `public` — see `docs/FINAL_IMPLEMENTATION_PLAN.md` §10.3. |
| `DATA_DIR` | only if `DATABASE_URL` is unset | `/var/data` — the disk mount path for the JSON fallback. Unset with no `DATABASE_URL` either, the app writes to `backend/data/`, wiped on every deploy. |
| `FRONTEND_ORIGIN` | yes | The Vercel production origin. Comma-separate to allow several. `localhost:5173` is always allowed; the list is never `*`. |
| `PYTHON_VERSION` | recommended | `3.11.9`, matching the version the model artifact is loaded under. |

Running with `DATABASE_URL` set still benefits from the disk as a safety net
during the Postgres migration window — keep both configured until the team is
confident in the Postgres path; the disk costs nothing extra once already
paying for a persistent-disk instance type.

`GEMINI_API_KEY` is **not** required. No code on the released path reads it —
see "Gemini" below.

## Vercel

No `vercel.json` is needed: Vercel detects Vite and the defaults are correct.
Configure the project once, in the dashboard:

- **Root directory:** `frontend`
- **Framework preset:** Vite
- **Build command:** `npm run build`
- **Output directory:** `dist`
- **Environment variable:** `VITE_API_BASE_URL` (Production, and Preview if used)

`VITE_*` variables are read at **build time**. After changing it, redeploy —
editing the variable alone does not update an existing build.

## Render

`render.yaml` in the repository root describes the service, including the disk.
Create it via **New → Blueprint** and point Render at this repository, then set
`FRONTEND_ORIGIN` in the dashboard (it is marked `sync: false` because the
Vercel URL does not exist until the frontend is deployed).

Notable settings, if creating the service by hand instead:

- **Root directory:** `backend`
- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Disk:** mount at `/var/data`, 1 GB
- **Health check:** `/monitoring/model`

A persistent disk requires a paid instance type. On the free tier the service
also sleeps when idle, and the first request after sleeping takes tens of
seconds while scikit-learn and the artifact load — avoid that for a live demo.

## Order of operations

1. Deploy the backend on Render (`FRONTEND_ORIGIN` can be blank for now) and
   note its URL.
2. Deploy the frontend on Vercel with `VITE_API_BASE_URL` set to that URL.
3. Set `FRONTEND_ORIGIN` on Render to the Vercel URL; Render restarts itself.
4. Verify, in this order:
   - `GET <api>/monitoring/model` reports `synthetic_ml`, `synthetic_if_v1`,
     `live_inference: true`, and artifact SHA-256 `8114caf6…f641a2`.
   - Open the Vercel URL, run the demo candidate, approve, dose, and advance
     monitoring to a RED transition.
   - Redeploy the backend and confirm the participant is still there — that is
     the disk doing its job.

## Persistence

**With `DATABASE_URL` set (recommended):** every write goes through
PostgreSQL — real foreign keys, a partial unique index that makes duplicate
detection structurally impossible once obligations exist, and one transaction
per approval-and-send once `ExecutionService` ships. Nothing here is
Supabase-specific; the application talks plain SQLAlchemy over
`postgresql+psycopg://`, so any PostgreSQL 15+ works.

**With `DATABASE_URL` unset:** `DATA_DIR` sets the JSON store directory; the
file names and shapes are unchanged from Phase 1/2. Writes are atomic (temp
file, then `os.replace`), so an interrupted deploy cannot leave a truncated
store. The disk is a single volume attached to a single instance — do not
scale this service beyond one instance while on the JSON backend, since two
would each hold their own cache of the same files and overwrite each other.
(PostgreSQL removes this constraint; the process still runs a single worker
for now regardless, since nothing yet needs more — see
`docs/FINAL_IMPLEMENTATION_PLAN.md` §11.6.)

To reset the JSON-backed demo, delete `store.json` and `monitoring.json` from
the disk via a Render shell; both are recreated on the next write. To reset
the Postgres-backed demo, run `alembic downgrade base && alembic upgrade
head` against `DATABASE_URL`, then re-seed via `POST /screen` /
`POST /screen/pdf` as usual.

## Supabase

Supabase is used purely as a managed PostgreSQL host — no PostgREST, no
`supabase-js`, no Supabase Auth. Set up:

1. Create a Supabase project (a **separate** one for development and for
   production — see `docs/FINAL_IMPLEMENTATION_PLAN.md` §10.2).
2. Copy the **session-mode** (Supavisor, port `5432`) connection string, not
   the transaction-mode pooler on `6543` — SQLAlchemy manages its own pool,
   and session mode preserves prepared statements.
3. Set `DATABASE_URL` on Render (and `.env.local` for development) to that
   string with the `postgresql+psycopg://` scheme.
4. Run `alembic upgrade head` once against it (from a developer machine, or a
   Render one-off job) before the service's first request.
5. In the Supabase dashboard, confirm the `trialguard` schema is **not**
   added to the exposed-schemas list — the application's tables carry patient
   identifiers and must never be reachable through the project's anon key.

`MIGRATION_DATABASE_URL` is a separate variable (defaulting to `DATABASE_URL`)
specifically so Alembic can be pointed at a **direct** connection if the
deployment ever puts a transaction-mode pooler in front of `DATABASE_URL` —
DDL does not survive that pooler.

## Gemini

`GEMINI_API_KEY` exists in a local, git-ignored `.env.local`, and is not used at
runtime. The only references are precomputed `gemini_explanation` strings inside
a static fixture read by the `synthetic` fixture provider, which the deployment
does not select. `RISK_PROVIDER=synthetic_ml` runs the Isolation Forest and
touches none of it. Do not configure the key in production, and never expose it
through a `VITE_` variable.
