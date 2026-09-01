# Smart Rental Tracking System — Frontend

React + TypeScript operations console for the FastAPI backend in this repo.
Live map with animated markers and geofences, breadcrumb playback, alert inbox,
demand forecasting and a fleet table.

## Run it

The backend must be up first — the dev server proxies `/api` to it.

```bash
cd .. && uvicorn app.main:app --reload
```

```bash
npm install
npm run dev
```

Open <http://localhost:5173>. `npm run build` produces a static `dist/` that any
web server or CDN can host.

| Script | What it does |
|---|---|
| `npm run dev` | Vite dev server on :5173, proxying `/api` → :8000 |
| `npm run build` | Typecheck (`tsc -b`) then production bundle |
| `npm run preview` | Serve the built bundle |
| `npm run lint` | oxlint |

## Stack, and why each piece

| Layer | Choice | Why this one |
|---|---|---|
| Build | **Vite** | The backend already serves the API, so there is nothing for Next.js's server half to do. A static SPA deploys to any CDN. |
| Maps | **MapLibre GL** | The only option in the brief that needs no API token or billing account. Mapbox and Google both gate on a key; a fresh clone here just works. |
| Real-time | **SSE** | The backend already ships `GET /api/stream/assets`, and the traffic is one-way. WebSockets would add a handshake and a reconnect loop for nothing; MQTT would add a broker. |
| Server state | **TanStack Query** | Caching, refetch and invalidation for ~20 endpoints, without hand-rolling any of it. |
| UI state | **Zustand** | Filters, selection, playback transport, theme. Redux Toolkit's ceremony buys nothing at this size. |
| Styling | **Tailwind** | Utility classes over CSS-variable design tokens, so light/dark swaps in one place. |
| Charts | **ECharts** | Bound directly (`components/EChart.tsx`) rather than via a wrapper package, so there is no peer-dependency lag behind React 19. |
| Tables | **TanStack Table** | Headless, so rows wear this app's tokens instead of a vendor theme. AG Grid earns its keep at virtualised five-figure row counts; this fleet is 21. |

## Layout

| Path | What lives there |
|---|---|
| `src/lib/types.ts` | Wire types mirrored from `app/schemas.py` |
| `src/lib/api.ts` | Fetch wrapper — the single place auth headers are injected |
| `src/lib/palette.ts` | Colour roles: categorical slots, reserved status palette |
| `src/hooks/queries.ts` | One hook per endpoint |
| `src/hooks/useLiveStream.ts` | The SSE connection and cache patching |
| `src/store/` | Zustand: session, filters, selection, playback, theme |
| `src/map/LiveMap.tsx` | MapLibre: animated markers, geofence rings, trails |
| `src/pages/chartOptions.ts` | Every chart option builder, in one file |
| `src/pages/` | Overview, Map, Assets, Asset detail, Add asset, Alerts, Analytics, Scan |

## Decisions worth defending

**One socket, and it patches the cache.** The simulator emits ~13 `asset_state`
frames every five seconds. Refetching on each one would be a stampede, so
`useLiveStream` writes frames straight into the TanStack Query cache and the map
and table both re-render from it. Neither view owns the connection, and the
periodic refetch in `queries.ts` reconciles filter membership the stream cannot
know about.

**Markers animate; they do not teleport.** Each asset's position is interpolated
over ~1.6 s toward its newest ping, easing out. A mid-flight update starts the
next leg from where the marker actually is, so it never snaps backwards. The
whole loop runs in refs inside one `requestAnimationFrame` — a moving fleet
causes zero React renders.

**Assets are a GeoJSON layer, not DOM markers.** 21 markers would be fine either
way; 10 000 would not, and the layer costs nothing extra to write. Site name
labels *are* DOM markers, because a symbol layer would need a glyph server and
the raster style deliberately has no external font dependency.

**The style object is built per map instance.** MapLibre takes ownership of the
style it is handed, so a shared module constant leaves the second `Map` with a
consumed style that silently never fires `load` — blank canvas, no error. React
StrictMode mounts every effect twice in dev, so a shared constant fails exactly
there. `mapStyle()` returns a fresh object each time.

**Colour follows the entity, never the rank.** Equipment types hold fixed
categorical slots, so filtering the fleet never repaints the survivors. The
status palette (good / warning / serious / critical) is reserved and never
doubles as a series colour, and every status ships an icon and a text label
beside the hue so nothing rests on colour alone.

**One axis, always.** Engine and idle hours share a unit, so they stack on a
single scale. Where two measures genuinely differ in scale they get two charts,
never a second y-axis.

**The forecast says which model answered.** The backend degrades from
Holt-Winters to exponential smoothing to a moving average depending on how much
history a slot has, and reports `null` MAPE when there is too little history to
claim an error. The chart footnote surfaces both rather than presenting every
prediction as equally confident.

**Fixed and movable plant are different animals.** Registering an asset asks one
question first, because it changes everything downstream:

* **Movable** — mobile plant. It gets checked out to a site, tracked, and
  geofenced. Its live site comes from whatever rental it is on, so the home yard
  on the form is only where it returns to, and it is optional.
* **Fixed** — installed plant: a tower crane, a generator, a batching plant. It
  is never rented out, which means it has *no rental to read a location from*.
  So the install site is mandatory, and the backend pins the asset to it
  permanently — without that, every fixed asset would project as site-less and
  read as `UNACCOUNTED` forever. Rental-shaped rules (overdue, geofence breach)
  do not apply to it; `derive_fixed_status()` handles it separately, and the one
  failure mode it does have is going quiet, which still reads as `UNACCOUNTED`.

`MOVABLE` is the server-side default, so every asset that existed before this
shipped keeps its old behaviour.

**Idempotency keys are minted per attempt, not per submit.** The check-in/out
screen holds one key across retries and regenerates it only after a success, so
a flaky-connection double submit returns the existing rental instead of
double-booking — which is the contract the backend already implements.

## Authentication — read this before deploying

**The backend ships no authentication.** There is no token endpoint, no user
table, and every route is open. `src/store/auth.ts` is therefore a client-side
session *shell*, not a security boundary: it sets a display identity, stores a
fake token, and gates the client routes. Anyone can still call the API directly.

It exists so the integration seam is already in place — token storage, bearer
injection in `lib/api.ts`, and the route guard in `App.tsx`. Wiring a real
OAuth2 / Keycloak / Auth0 issuer means changing `signIn` and adding
dependencies to the FastAPI routes. Do both before this is exposed anywhere real.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `VITE_API_BASE` | *(empty)* | Empty uses the dev proxy. Set to an absolute origin when the frontend is hosted separately from the API. |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | Where the dev server forwards `/api` |

The map's basemap is OpenStreetMap raster tiles, which means **the map needs
internet access at runtime**. For an air-gapped deployment, point `mapStyle()`
in `src/map/LiveMap.tsx` at a self-hosted tile server; nothing else changes.
