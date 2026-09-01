/**
 * Live map page: animated markers, geofence rings, breach panel, filter bar.
 * Filters sit in one row above the map, and the same store backs the asset
 * table, so switching views keeps the reader's filter.
 */
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { LiveMap } from "@/map/LiveMap";
import { Card, ErrorNote, Spinner, StatusChip, Empty, inputClass } from "@/components/primitives";
import { useBreaches, useMapSnapshot, useSites } from "@/hooks/queries";
import { useFilters, useSelection } from "@/store/ui";
import { useLive } from "@/hooks/useLiveStream";
import { num, timeAgo } from "@/lib/format";
import { TYPE_ORDER } from "@/lib/palette";
import type { AssetStatus } from "@/lib/types";

const STATUSES: AssetStatus[] = ["IN_USE", "IDLE", "AVAILABLE", "OVERDUE", "UNACCOUNTED"];

export default function MapPage() {
  const snapshot = useMapSnapshot();
  const sites = useSites();
  const breaches = useBreaches();
  const { selectedId, select } = useSelection();
  const { search, status, type, siteId, breachesOnly, setFilter, reset } = useFilters();
  const streamStatus = useLive((s) => s.status);

  const assets = useMemo(() => {
    const all = snapshot.data?.assets ?? [];
    const q = search.trim().toLowerCase();
    return all.filter((a) => {
      if (status && a.status !== status) return false;
      if (type && a.type !== type) return false;
      if (siteId && a.site_id !== siteId) return false;
      if (breachesOnly && !a.outside_geofence) return false;
      if (q && !(a.equipment_id.toLowerCase().includes(q) || a.type.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [snapshot.data, search, status, type, siteId, breachesOnly]);

  const mapSites = useMemo(() => {
    const rows = snapshot.data?.sites ?? [];
    return siteId ? rows.filter((s) => s.site_id === siteId) : rows;
  }, [snapshot.data, siteId]);

  const activeFilters = Boolean(search || status || type || siteId || breachesOnly);

  if (snapshot.isLoading) return <Spinner label="Loading map" />;
  if (snapshot.isError) return <div className="p-6"><ErrorNote error={snapshot.error} /></div>;

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-hair bg-surface px-5 py-3">
        <div className="mr-2">
          <h1 className="text-base font-semibold text-ink">Live Map</h1>
          <p className="text-xs text-ink-muted">
            {assets.length} of {snapshot.data?.assets.length ?? 0} assets ·{" "}
            <span className={streamStatus === "live" ? "text-good" : "text-warning"}>{streamStatus}</span>
          </p>
        </div>

        <input
          className={inputClass + " w-44"}
          placeholder="Search asset…"
          value={search}
          onChange={(e) => setFilter("search", e.target.value)}
        />
        <select className={inputClass} value={status} onChange={(e) => setFilter("status", e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace("_", " ")}
            </option>
          ))}
        </select>
        <select className={inputClass} value={type} onChange={(e) => setFilter("type", e.target.value)}>
          <option value="">All types</option>
          {TYPE_ORDER.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select className={inputClass} value={siteId} onChange={(e) => setFilter("siteId", e.target.value)}>
          <option value="">All sites</option>
          {(sites.data ?? []).map((s) => (
            <option key={s.site_id} value={s.site_id}>
              {s.name}
            </option>
          ))}
        </select>
        <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-hair px-2.5 py-1.5 text-sm text-ink-2">
          <input
            type="checkbox"
            className="accent-[var(--accent)]"
            checked={breachesOnly}
            onChange={(e) => setFilter("breachesOnly", e.target.checked)}
          />
          Breaches only
        </label>
        {activeFilters && (
          <button onClick={reset} className="text-xs text-ink-muted hover:text-ink">
            Clear
          </button>
        )}
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <LiveMap assets={assets} sites={mapSites} selectedId={selectedId} onSelect={select} />

          <div className="pointer-events-none absolute bottom-6 right-3 z-10 rounded-lg border border-hair bg-surface/95 p-2.5 text-xs backdrop-blur">
            <div className="mb-1.5 font-medium text-ink">Status</div>
            {STATUSES.map((s) => (
              <div key={s} className="flex items-center gap-2 py-0.5 text-ink-2">
                <StatusChip status={s} />
              </div>
            ))}
            <div className="mt-1.5 flex items-center gap-2 border-t border-hair pt-1.5 text-ink-2">
              <span className="inline-block h-3 w-3 rounded-full border-2 border-critical" />
              Outside geofence
            </div>
          </div>
        </div>

        <aside className="w-72 shrink-0 overflow-y-auto border-l border-hair bg-surface">
          <Card title="Geofence breaches" subtitle="On-rent assets outside their site" bodyClassName="p-0" className="border-0 rounded-none">
            {breaches.isLoading ? (
              <Spinner />
            ) : (breaches.data ?? []).length === 0 ? (
              <Empty>All assets are inside their geofence.</Empty>
            ) : (
              <ul className="divide-y divide-hair">
                {(breaches.data ?? []).map((b) => (
                  <li key={b.equipment_id}>
                    <button
                      onClick={() => select(b.equipment_id)}
                      className={
                        "w-full px-4 py-3 text-left transition-colors hover:bg-ink-muted/5 " +
                        (selectedId === b.equipment_id ? "bg-[var(--accent)]/10" : "")
                      }
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-ink">{b.equipment_id}</span>
                        <span className="text-xs font-semibold text-critical tnum">+{num(b.overshoot_km)} km</span>
                      </div>
                      <p className="mt-0.5 text-xs text-ink-muted">
                        {num(b.distance_km)} km from {b.site_name} ({num(b.radius_km, 0)} km fence)
                      </p>
                      <p className="text-[10px] text-ink-muted">seen {timeAgo(b.last_seen_at)}</p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {selectedId && (
            <div className="border-t border-hair p-4">
              <Link
                to={`/assets/${selectedId}`}
                className="block rounded-lg bg-[var(--accent)] px-3 py-2 text-center text-sm font-medium text-white hover:opacity-90"
              >
                Open {selectedId} →
              </Link>
              <button onClick={() => select(null)} className="mt-2 w-full text-xs text-ink-muted hover:text-ink">
                Clear selection
              </button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
