# Smart Rental Tracking System — Backend

Event-sourced asset rental tracking for construction and mining fleets.
FastAPI + SQLAlchemy + scikit-learn. SQLite for zero-setup dev, Postgres in prod
via one environment variable.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

First boot seeds the demo fleet, runs the overdue scan, the anomaly scan and the
forecaster, then starts the background scheduler. Interactive API docs at
<http://localhost:8000/docs>.

```bash
pytest -q          # 43 tests
```

With Docker (Postgres included):

```bash
docker compose up --build
```

## Frontend

A React + TypeScript console lives in [`frontend/`](frontend/README.md) — live
map with animated markers and geofences, breadcrumb playback, alert inbox,
forecasting and a fleet table. Run the API first, then:

```bash
cd frontend && npm install && npm run dev
```

It proxies `/api` to this backend on :8000 and consumes the SSE stream directly.

## Architecture in one paragraph

Every state change is appended to `asset_events` and never updated. Current
state (`asset_current_state`), usage aggregates and analytics are **projections**
— drop them, call `POST /api/admin/rebuild-projections`, and they come back.
That is what makes new dashboard metrics cheap, gives a free audit trail for
"where was this asset in March", and lets the ingest path move to Kafka later
without touching domain code.

```
clients ──REST──> API (stateless)  ──> domain services ──> event log
        └──SSE──> stream                                     │
                                                    projections + analytics
workers (overdue · anomaly · forecast · simulator) ──────────┘
adapters: scanner (QR│RFID│manual) · notifier (in-app│email│push) · telemetry (sim│MQTT)
```

The three adapter interfaces are the "simulate now, real later" seam: swapping
the demo simulator for a real MQTT feed means implementing `poll()`, nothing else.

## Layout

| Path | What lives there |
|---|---|
| `app/models.py` | Schema. Event log, projections, outputs |
| `app/domain/` | Business logic, framework-free and unit-testable |
| `app/ml/` | Feature engineering, forecasting, anomaly detection |
| `app/adapters/` | Scanner, notifier, telemetry source, SSE bus |
| `app/api/` | Thin HTTP routers over the domain |
| `app/workers/` | Scheduled jobs (same callables Celery would run) |
| `app/seed.py` | Demo fleet, including the problem-statement assets |
| `db/partitions.sql` | Postgres partitioning + partial indexes for scale |
| `frontend/` | React + TypeScript console (Vite, MapLibre, TanStack Query) |

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/overview` | Dashboard header: counts, KPIs, savings |
| `POST /api/equipment` | Register a machine (movable or fixed); mints ID, QR payload, RFID tag |
| `PATCH /api/equipment/{id}` | Edit rate, model, service interval, RFID |
| `GET /api/equipment/{id}/label` | What the yard prints on the sticker |
| `POST /api/equipment/{id}/service` | Log a completed service, reset the clock |
| `POST /api/equipment/{id}/retire` | Retire (never delete - the log stays whole) |
| `POST /api/sites`, `PATCH /api/sites/{id}` | Sites with a geofence radius |
| `POST /api/operators` | Add an operator |
| `GET /api/map` | Map snapshot: markers + site geofence rings |
| `GET /api/assets/{id}/track` | Breadcrumb trail, replayed from the event log |
| `GET /api/geofence/breaches` | Assets outside their assigned site |
| `GET /api/assets` | Live asset list (`status`, `site_id`, `type`, `search`) |
| `GET /api/assets/{id}` | Detail: usage, timeline, alerts, maintenance |
| `GET /api/stream/assets` | SSE live status + alert push |
| `POST /api/scan/resolve` | Preview what a scan resolved to |
| `POST /api/checkout` · `/api/checkin` | The core journey |
| `POST /api/telemetry` · `/telemetry/batch` | Usage ingest |
| `GET /api/usage?group_by=asset\|site\|type` | Usage summaries |
| `GET /api/alerts` · `POST /api/alerts/{id}/acknowledge` | Alert inbox |
| `GET /api/forecast` · `/forecast/shortages` | Demand predictions |
| `GET /api/anomalies` | Detections with reasons |
| `GET /api/optimize/recommendations` | Ranked actions with rupee impact |
| `POST /api/admin/seed` · `/admin/jobs/{job}/run` | Demo controls |

## Decisions worth defending

**Idempotency on every write.** Site connectivity is bad, so the mobile client
queues scans offline and flushes on reconnect. A replayed check-out returns the
rental it already created instead of a 409, and a replayed telemetry tick does
not inflate the day's hours. Both are tested.

**Status is derived, never stored.** `derive_status()` is a pure function of
(rental, hours, last ping). It also emits `health_flags` explaining the verdict,
so the UI can say *why* something is `UNACCOUNTED`, not just that it is.

**Rules before ML.** Six deterministic rules fire first and each ships a
human-readable reason plus the evidence behind it. IsolationForest runs second
for combinations nobody wrote a rule for. Final severity is the max of the two.
The ML score is deliberately *not* min-max normalised — normalising forces the
worst row in any batch to 1.0, which would make a perfectly healthy fleet always
produce a top "anomaly". `contamination="auto"` fixes the boundary at 0.5 so a
uniform fleet scores flat.

**The forecaster degrades instead of erroring.** Holt-Winters at ≥12 weeks of
history, simple exponential smoothing at ≥6, moving-average blend below that.
Every prediction reports which model answered and its backtested MAPE — or `null`
when there is not enough history to claim an error honestly.

**The trail has no table.** Location history is reconstructed from `asset_events`
- every ping already carried its coordinates, so the breadcrumbs were there
before the endpoint was. Add a positions table when read volume demands it; the
API contract will not change.

**Fixed plant is not a rental.** Equipment carries a `mobility` of `MOVABLE`
(default) or `FIXED`. Installed plant -- a tower crane, a generator -- is never
checked out, so it has no rental to take a site from; it is pinned to its
`home_site_id` instead, and `derive_fixed_status()` judges it without the
rental-shaped branches (overdue, expected return, operator) that mean nothing for
a machine bolted to a slab. A fixed asset with no site is rejected at creation,
because it could never be placed on the map.

**The assistant reads the same read-models as the screen.** Mira, the sphere in
the bottom-right corner, is a Gemini model given seven query tools -- and only
those seven, all of which read this fleet. She is never asked to recall anything
about the fleet from training, and every turn carries a fresh snapshot of it, so
her answers agree with the dashboard by construction rather than by luck. An
off-topic question has no tool to reach for, which is why the scope holds
without a keyword filter policing it. None of the tools write: she can tell you
that EQX1002 is unaccounted for and what it is costing, but she cannot check it
in. She is off unless `GEMINI_API_KEY` is set, and the button hides itself when
she cannot answer.

**A day cannot exceed 24 hours.** Enforced at ingest, so a fast or retrying
source cannot produce impossible rows that then poison every downstream z-score.

## Scaling path

Nothing below changes domain code — each row is an infrastructure swap behind an
interface that already exists.

| | Now | 10k assets | 1M assets |
|---|---|---|---|
| Ingest | HTTP → Postgres | Redis buffer + batch insert | Kafka consumer group |
| Telemetry | Partitioned table | TimescaleDB hypertable | Timescale + S3 cold tier |
| API | 1 process | N replicas (already stateless) | + regional read replicas |
| SSE | in-process bus | Redis pub/sub fanout | dedicated push service |
| Jobs | APScheduler | Celery workers | scheduled batch cluster |
| Projections | sync on write | async off the event log | materialized views + CDC |

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./smartrental.db` | Postgres URL swaps engines, no code change |
| `CORS_ORIGINS` | localhost:5173,3000 | Comma-separated |
| `SIMULATOR_ENABLED` | `true` | Turn off against a real telemetry feed |
| `SIMULATOR_TICK_SECONDS` | `5` | Demo cadence |
| `SIMULATOR_HOURS_PER_TICK` | `0.05` | 3 minutes of machine time per tick |
| `IDLE_RATIO_THRESHOLD` | `0.70` | Excessive-idle rule |
| `STALE_PING_HOURS` | `48` | Beyond this, an asset reads as unaccounted |
| `OVERDUE_REMINDER_DAYS` | `3` | Lead time on due-soon alerts |

## Demo data

The seven assets from the problem statement keep their exact usage signature, so
the detections on stage are real, not scripted:

| Asset | Signature | What fires |
|---|---|---|
| EQX1001 | 1.5 engine / 10 idle | 87% idle → `EXCESSIVE_IDLE`, return-early recommendation |
| EQX1002 | 0 engine / 11 idle, no site, no operator | `UNASSIGNED_SITE` + `ZERO_ENGINE_HOURS`, CRITICAL |
| EQX1003 | 7.5 / 0.5 | healthy baseline — no alerts |
| EQX1004 | 2 / 9, past due | `OVERDUE` with accrued cost |
| EQX1005 | 8 / 0 | best in fleet |
| EQX1006 | 3 / 6, 14.4 km off site | `GEOFENCE_BREACH`, CRITICAL |
| EQX1007 | 0 engine / 12 idle, no site | ghost asset |

Thirteen more assets and 40 weeks of closed rentals give the forecaster real
history to train on.
