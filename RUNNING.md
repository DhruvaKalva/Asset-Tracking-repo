# Running the Smart Rental Tracking System

Everything needed to get the API and the dashboard up on a clean machine, plus
what to do when it does not work. Two processes: a FastAPI backend on `:8000`
and a Vite dev server on `:5173`.

---

## What you need first

| | Version | Check with | Notes |
|---|---|---|---|
| Python | 3.10 or 3.11 | `python --version` | 3.12+ untested — `numpy==1.26.4` has no wheel for it |
| Node.js | 18+ (20 LTS or newer preferred) | `node --version` | Only needed for the frontend |
| Git | any recent | `git --version` | |

Nothing else. Postgres and Docker are optional and covered at the bottom.

> **Windows note.** If `python` prints *"Python was not found; run without
> arguments to install from the Microsoft Store"*, you are hitting the Windows
> App Execution Alias, not a real interpreter. Install Python from
> [python.org](https://www.python.org/downloads/) or `winget install Python.Python.3.11`,
> then open a **new** terminal — `PATH` changes do not reach already-running shells.

---

## Quick start

Two terminals. Backend first — the frontend proxies to it and every panel will
error without it.

### Terminal 1 — backend

```bash
python -m venv .venv
```

```bash
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

```bash
uvicorn app.main:app --reload
```

First boot does a lot on its own: creates the schema, seeds the demo fleet,
runs the overdue scan, the anomaly scan and the forecaster, then starts the
background scheduler. Give it 10–20 seconds. You will know it is ready when the
log prints `API ready`.

- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

### Terminal 2 — frontend

```bash
cd frontend
```

```bash
npm install
```

```bash
npm run dev
```

Open <http://localhost:5173>. Sign in with any name — the backend has no
authentication, so the login screen only sets a display identity (see
[Security](#security-read-this-before-you-deploy)).

---

## Verifying it actually works

```bash
python -m pytest -q
```

Expect `47 passed`. This is the fastest way to tell whether a problem is your
environment or the code.

```bash
cd frontend && npm run build
```

Expect a clean `tsc -b` followed by a bundle. Typecheck failures show up here
before they show up in the browser.

A three-second smoke test of the whole stack:

```bash
curl http://localhost:8000/api/overview
```

If that returns JSON with `total_assets`, the database, the seed, the
projections and the API are all working.

---

## What you should see

| Page | What it proves |
|---|---|
| **Overview** | Seeded fleet, KPIs, live event ticker. The sidebar pill reads **Live** in green. |
| **Live Map** | Markers moving every ~5 seconds, dashed geofence rings, breaches listed on the right. |
| **Assets** | 20 assets, sortable, filterable. Movable and fixed both listed. |
| **Asset detail** | Open `EQX1001` — 87% idle, an excessive-idle alert, and playback over its breadcrumb trail. |
| **Alerts** | Around 29 open, criticals first. Acknowledging one round-trips to the API. |
| **Analytics** | Forecast per equipment type, with the model that answered and its backtested error. |

The movement is a **simulator**, not real telemetry — it invents a tick for
every on-rent asset every five seconds. Turn it off with
`SIMULATOR_ENABLED=false` in `.env`.

---

## Configuration

Copy `.env.example` to `.env` and edit. Every value has a working default, so
an empty `.env` still runs.

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./smartrental.db` | A Postgres URL swaps engines with no code change |
| `CORS_ORIGINS` | `localhost:5173,3000` | Comma-separated |
| `SIMULATOR_ENABLED` | `true` | The switch that stops invented data |
| `SIMULATOR_TICK_SECONDS` | `5` | How often the simulator advances the fleet |
| `SIMULATOR_HOURS_PER_TICK` | `0.05` | 3 minutes of machine time per tick |
| `IDLE_RATIO_THRESHOLD` | `0.70` | Above this, an asset reads as excessively idle |
| `STALE_PING_HOURS` | `48` | Beyond this with no ping, an asset reads unaccounted |
| `OVERDUE_REMINDER_DAYS` | `3` | Lead time on due-soon alerts |
| `GEMINI_API_KEY` | *(empty)* | Enables Mira, the assistant. Empty means no Mira |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Any model your key can reach |

The frontend has its own `frontend/.env.example`. You only need it when hosting
the frontend separately from the API — in development the Vite proxy handles it.

---

## Mira, the dashboard assistant

The blue sphere in the bottom-right corner is Mira. She answers questions about
the fleet — utilisation, overdue hires, idle cost, what needs servicing — from
the same live data the dashboard renders.

**She is off by default.** She needs a Google Gemini API key:

1. Get one from [Google AI Studio](https://aistudio.google.com/apikey).
2. Put it in `.env`:

```bash
GEMINI_API_KEY=your-key-here
```

3. Restart the backend. `GET /health` should now report `"mira": true`.

Without a key the endpoint reports itself unconfigured and the button does not
render at all — an assistant that cannot answer is worse than no assistant, so
it does not advertise itself.

**The key is never committed.** `.env` is gitignored, so a fresh clone on
another machine has no Mira until someone sets a key there too. That is
deliberate: keys belong to machines, not to repositories.

### What she can and cannot do

She has exactly seven tools, and all seven read this fleet: fleet overview,
asset search, one asset's record, open alerts, utilisation, cost analysis, and
the site list. There is no tool for anything else, so an off-topic question has
nothing to draw on and she declines it in a line. She is told never to state a
figure that did not come from those tools or from the live snapshot attached to
every turn, so she cannot narrate a number that is not on screen.

She reads. She cannot check an asset in or out, raise or resolve an alert, or
change any record — the tools are queries, and none of them write.

Every answer shows which read-models produced it as small chips beneath the
reply, and equipment ids in her answers link straight to the asset page.

### Cost

Each turn sends a roughly 1,500-character fleet snapshot plus the conversation
so far — about 1,600–5,000 tokens depending on how many tools she needs. Most
questions are answered from the snapshot alone, with no tool call at all.

---

## Demo controls

Useful when showing the system or resetting after experimenting.

```bash
curl -X POST "http://localhost:8000/api/admin/seed?reset=true"
```

Rebuilds the demo fleet from scratch. **This deletes everything**, including
assets you added through the UI.

> `seed.py` defines 6 sites, but the database shipped with 7 — `S007 Madurai
> Bypass` exists only in the `.db` file. A reset drops it. Re-create it with
> `POST /api/sites` if you need it, or add it to `SITES` in `app/seed.py` to
> make it permanent.

```bash
curl -X POST http://localhost:8000/api/admin/simulator/tick
```

Advances the fleet one step by hand — handy with the simulator paused.

```bash
curl -X POST http://localhost:8000/api/admin/jobs/anomaly/run
```

Runs a job immediately instead of waiting for its schedule. Also accepts
`overdue` and `forecast`.

```bash
curl -X POST http://localhost:8000/api/admin/rebuild-projections
```

Drops the read model and replays it from the event log. If the dashboard still
looks right afterwards, the event-sourced design is doing its job.

---

## Troubleshooting

**Every panel shows an error, sidebar says "Offline".**
The backend is not running, or not on `:8000`. Check `curl http://localhost:8000/health`.

**`ModuleNotFoundError: No module named 'app'`**
You are not in the project root. `uvicorn` must be run from the directory
containing `app/`.

**`ImportError` around numpy, pandas or scikit-learn**
Almost always Python 3.12+. The pinned `numpy==1.26.4` has no wheel for it and
tries to build from source. Use 3.10 or 3.11.

**Port already in use**
`uvicorn app.main:app --port 8001` — then point the dev proxy at it. This must
be a real environment variable, not a `.env` entry: `vite.config.ts` reads
`process.env`, which Vite does not populate from `.env` files.

```bash
VITE_PROXY_TARGET=http://127.0.0.1:8001 npm run dev --prefix frontend
```

On PowerShell: `$env:VITE_PROXY_TARGET="http://127.0.0.1:8001"` first.

**The map is blank but the rest of the page renders.**
The basemap is OpenStreetMap raster tiles, so the map needs internet access at
runtime. Everything else works offline.

**`npm install` fails on `node-gyp` or Python errors**
Node is too old. Use 20 LTS or newer.

**Dashboard numbers look frozen.**
Check `curl http://localhost:8000/api/admin/jobs` — if `running` is false the
scheduler died. Restart the API.

**The "Ask Mira" sphere is missing.**
No API key. `curl http://localhost:8000/api/mira/health` — if `configured` is
false, set `GEMINI_API_KEY` in `.env` and restart the backend. The button is
hidden on purpose when she cannot answer.

**Mira says the key was rejected.**
The key is wrong, revoked, or from a project without the Generative Language
API enabled. Check it at [Google AI Studio](https://aistudio.google.com/apikey).

**Mira says there is no such model.**
Your key cannot reach `GEMINI_MODEL`. Set it to a model the key can use.

**Schema errors after pulling new code**
`init_db()` applies additive column migrations on boot, so restarting the API
usually fixes it. If a change was not additive, delete `smartrental.db` and let
it reseed.

---

## Docker

```bash
docker compose up --build
```

Brings up the API with Postgres instead of SQLite. The frontend is not in the
compose file — run it with `npm run dev` alongside.

## Postgres by hand

```bash
psql -d smartrental -f db/partitions.sql
```

Run this **before** the first boot — it creates `telemetry_daily` as a
partitioned table, which cannot be done after the ORM creates a plain one. Then
point `DATABASE_URL` at the database and start the API normally.

---

## Security — read this before you deploy

**The API has no authentication.** There is no token endpoint, no user table,
and every route is open, including `/api/admin/*`. The login screen sets a
display identity and nothing more.

This is fine on `localhost`. It is not fine on a network anyone else can reach.
Before exposing it: add an identity provider, put FastAPI dependencies on the
routes, and lock down the admin endpoints — a stranger can currently wipe your
database with one `curl`.

---

## Layout

| Path | What lives there |
|---|---|
| `app/` | FastAPI backend — domain, API, ML, adapters, workers |
| `frontend/` | React + TypeScript console ([its own README](frontend/README.md)) |
| `tests/` | 47 behaviour tests |
| `db/partitions.sql` | Postgres partitioning, applied by hand |
| `README.md` | Architecture and the decisions behind it |
