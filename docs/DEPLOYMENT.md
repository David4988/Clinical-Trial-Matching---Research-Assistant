# Deployment

TrialGuard AI is deployed as two services.

```
Vercel                          Render
static Vite build   ──HTTPS──▶  FastAPI (uvicorn)
                                      │
                                persistent disk
                                      │
                          /var/data/store.json
                          /var/data/monitoring.json
```

The backend is **not** serverless, and deliberately so. Screening results,
treatments, doses and monitoring cycles are written to JSON files, and a single
demo walks a dozen requests that must all see each other's writes. A serverless
function has an ephemeral, unshared filesystem, so the participant would vanish
mid-flow. Render gives the process a real disk that survives restarts and
redeploys.

Nothing about the application's behaviour changes between local and production:
same code paths, same JSON stores, same risk provider. Only three things are
configurable — where the API is, which browser origin may call it, and where
the JSON lives.

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
| `DATA_DIR` | yes | `/var/data` — the disk mount path. Unset, the app writes to `backend/data/`, which on Render would be wiped on every deploy. |
| `FRONTEND_ORIGIN` | yes | The Vercel production origin. Comma-separate to allow several. `localhost:5173` is always allowed; the list is never `*`. |
| `PYTHON_VERSION` | recommended | `3.11.9`, matching the version the model artifact is loaded under. |

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

`DATA_DIR` sets the directory; the file names and JSON shapes are unchanged.
Writes are atomic (temp file, then `os.replace`), so an interrupted deploy
cannot leave a truncated store.

The disk is a single volume attached to a single instance. Do not scale this
service beyond one instance — two would each hold their own cache of the same
files and overwrite each other.

To reset the demo, delete `store.json` and `monitoring.json` from the disk via a
Render shell; both are recreated on the next write.

## Gemini

`GEMINI_API_KEY` exists in a local, git-ignored `.env.local`, and is not used at
runtime. The only references are precomputed `gemini_explanation` strings inside
a static fixture read by the `synthetic` fixture provider, which the deployment
does not select. `RISK_PROVIDER=synthetic_ml` runs the Isolation Forest and
touches none of it. Do not configure the key in production, and never expose it
through a `VITE_` variable.
