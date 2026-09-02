/**
 * Asset detail: usage history, breadcrumb playback, alerts, timeline, maintenance.
 *
 * The playback transport replays the track the backend reconstructs from the
 * event log -- there is no positions table behind it, which is worth knowing when
 * a short window returns only a point or two.
 */
import { useEffect, useMemo, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { EChart } from "@/components/EChart";
import { dailyUsageOption } from "@/pages/chartOptions";
import { LiveMap } from "@/map/LiveMap";
import {
  Card,
  Empty,
  ErrorNote,
  SeverityChip,
  Spinner,
  StatusChip,
  buttonClass,
} from "@/components/primitives";
import { useAsset, useAssetPhotos, useAssetUsage, useTrack } from "@/hooks/queries";
import { usePlayback } from "@/store/ui";
import type { AssetPhoto } from "@/lib/types";
import { dueLabel, formatDate, formatDateTime, hours, money, num, pct, timeAgo, titleCase } from "@/lib/format";

const WINDOWS = [6, 24, 72, 168];
const SPEEDS = [1, 4, 16];

export default function AssetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const detail = useAsset(id);
  const usage = useAssetUsage(id, 30);
  const photos = useAssetPhotos(id);
  const { playing, cursor, speed, windowHours, setPlaying, setCursor, setSpeed, setWindowHours, reset } = usePlayback();
  const track = useTrack(id, windowHours);

  const points = useMemo(() => track.data?.points ?? [], [track.data]);

  // Reset the transport when the asset or window changes.
  useEffect(() => {
    reset();
  }, [id, windowHours, reset]);

  // Playback clock. One interval, cancelled on pause/unmount; the cursor is the
  // single source of truth for both the trail head and the scrubber.
  const rafRef = useRef<number | null>(null);
  useEffect(() => {
    if (!playing || points.length < 2) return;
    const stepMs = 900 / speed;
    let last = performance.now();

    const tick = (now: number) => {
      if (now - last >= stepMs) {
        last = now;
        const next = usePlayback.getState().cursor + 1;
        if (next >= points.length) {
          setCursor(points.length - 1);
          setPlaying(false);
          return;
        }
        setCursor(next);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, speed, points.length, setCursor, setPlaying]);

  const usageChart = useMemo(() => dailyUsageOption(usage.data?.daily ?? []), [usage.data]);

  if (detail.isLoading) return <Spinner label="Loading asset" />;
  if (detail.isError) return <div className="p-6"><ErrorNote error={detail.error} /></div>;

  const { asset, alerts, timeline, maintenance } = detail.data!;
  const head = points[Math.min(cursor, Math.max(0, points.length - 1))];
  const trailToHead = points.slice(0, Math.min(cursor + 1, points.length));

  return (
    <div className="space-y-4 p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold text-ink">{asset.equipment_id}</h1>
            <StatusChip status={asset.status} />
            {asset.mobility === "FIXED" && (
              <span className="inline-flex items-center gap-1 rounded-full border border-hair px-2 py-0.5 text-xs text-ink-2">
                <span aria-hidden>⚓</span> Fixed — installed plant
              </span>
            )}
          </div>
          <p className="mt-0.5 text-sm text-ink-muted">
            {asset.type}
            {asset.model && ` · ${asset.model}`} · {asset.site_name ?? "Unassigned"}
            {asset.mobility === "MOVABLE" && ` · ${asset.operator_name ?? "no operator"}`} · seen{" "}
            {timeAgo(asset.last_seen_at)}
          </p>
        </div>
        <Link to="/assets" className={buttonClass}>
          ← All assets
        </Link>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Mini label="Utilisation today" value={pct(asset.utilization_pct)} />
        <Mini label="Engine today" value={hours(asset.engine_hours_today)} />
        <Mini label="Idle today" value={hours(asset.idle_hours_today)} />
        <Mini label="Rate" value={`${money(asset.rental_rate_per_hour)}/h`} />
        <Mini
          label="Due"
          value={dueLabel(asset.days_until_due)}
          tone={asset.days_until_due != null && asset.days_until_due < 0 ? "text-serious" : undefined}
        />
      </div>

      {Object.keys(asset.health_flags ?? {}).length > 0 && (
        <Card title="Why this status" subtitle="health_flags, straight from derive_status()">
          <div className="flex flex-wrap gap-2">
            {Object.entries(asset.health_flags).map(([k, v]) => (
              <span key={k} className="rounded-lg border border-hair px-2.5 py-1 text-xs text-ink-2">
                <span className="text-ink-muted">{titleCase(k)}:</span>{" "}
                <span className="tnum font-medium text-ink">
                  {typeof v === "boolean" ? (v ? "yes" : "no") : typeof v === "number" ? num(v, 2) : String(v)}
                </span>
              </span>
            ))}
          </div>
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card
          title="Location playback"
          subtitle={`${track.data?.point_count ?? 0} points · ${num(track.data?.distance_km ?? 0)} km travelled`}
          bodyClassName="p-0"
        >
          <div className="h-[320px]">
            <LiveMap
              assets={
                asset.lat != null && asset.lng != null
                  ? [
                      {
                        equipment_id: asset.equipment_id,
                        type: asset.type,
                        status: asset.status,
                        lat: asset.lat,
                        lng: asset.lng,
                        site_id: asset.site_id,
                        site_name: asset.site_name,
                        last_seen_at: asset.last_seen_at,
                        distance_from_site_km: track.data?.distance_from_site_km ?? null,
                        outside_geofence: Boolean(track.data?.distance_from_site_km && track.data?.site && track.data.distance_from_site_km > track.data.site.radius_km),
                      },
                    ]
                  : []
              }
              sites={track.data?.site ? [track.data.site] : []}
              selectedId={null}
              onSelect={() => {}}
              trail={trailToHead}
              playhead={head ? { lat: head.lat, lng: head.lng } : null}
              fitTo={points.length > 1 ? points.map((p) => [p.lng, p.lat] as [number, number]) : null}
            />
          </div>

          <div className="space-y-2 border-t border-hair p-3">
            <div className="flex flex-wrap items-center gap-2">
              <button
                className={buttonClass}
                disabled={points.length < 2}
                onClick={() => {
                  if (cursor >= points.length - 1) setCursor(0);
                  setPlaying(!playing);
                }}
              >
                {playing ? "⏸ Pause" : "▶ Play"}
              </button>
              <button className={buttonClass} onClick={() => { setPlaying(false); setCursor(0); }}>
                ⏮ Reset
              </button>

              <div className="flex items-center gap-1 text-xs text-ink-muted">
                Speed
                {SPEEDS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSpeed(s)}
                    className={
                      "rounded px-1.5 py-0.5 " +
                      (speed === s ? "bg-[var(--accent)]/15 font-medium text-[var(--accent)]" : "hover:text-ink")
                    }
                  >
                    {s}×
                  </button>
                ))}
              </div>

              <div className="ml-auto flex items-center gap-1 text-xs text-ink-muted">
                Window
                {WINDOWS.map((w) => (
                  <button
                    key={w}
                    onClick={() => setWindowHours(w)}
                    className={
                      "rounded px-1.5 py-0.5 " +
                      (windowHours === w ? "bg-[var(--accent)]/15 font-medium text-[var(--accent)]" : "hover:text-ink")
                    }
                  >
                    {w < 24 ? `${w}h` : `${w / 24}d`}
                  </button>
                ))}
              </div>
            </div>

            <input
              type="range"
              min={0}
              max={Math.max(0, points.length - 1)}
              value={Math.min(cursor, Math.max(0, points.length - 1))}
              onChange={(e) => {
                setPlaying(false);
                setCursor(Number(e.target.value));
              }}
              disabled={points.length < 2}
              className="w-full accent-[var(--accent)]"
            />
            <div className="flex justify-between text-[11px] text-ink-muted">
              <span>{points[0] ? formatDateTime(points[0].at) : "—"}</span>
              <span className="font-medium text-ink">{head ? formatDateTime(head.at) : "no track in this window"}</span>
              <span>{points.at(-1) ? formatDateTime(points.at(-1)!.at) : "—"}</span>
            </div>
          </div>
        </Card>

        <Card title="Usage, last 30 days" subtitle="Engine and idle hours per day, one shared axis">
          {usage.isLoading ? <Spinner /> : <EChart option={usageChart} height={320} />}
        </Card>
      </div>

      <Card
        title={`Condition photos (${photos.data?.length ?? 0})`}
        subtitle="Out and back, side by side — the pair a damage claim is settled on"
      >
        {photos.isLoading ? (
          <Spinner />
        ) : (photos.data ?? []).length === 0 ? (
          <Empty>
            No photos yet. They are captured on the Check In/Out page when this asset changes hands.
          </Empty>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2">
            <PhotoSet
              label="Going out"
              rows={(photos.data ?? []).filter((p) => p.kind === "CHECK_OUT")}
            />
            <PhotoSet
              label="Coming back"
              rows={(photos.data ?? []).filter((p) => p.kind === "CHECK_IN")}
            />
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={`Open alerts (${alerts.length})`} bodyClassName="p-0">
          {alerts.length === 0 ? (
            <Empty>No open alerts.</Empty>
          ) : (
            <ul className="divide-y divide-hair">
              {alerts.map((a) => (
                <li key={a.alert_id} className="px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <SeverityChip severity={a.severity} />
                    <span className="text-[10px] text-ink-muted">{timeAgo(a.raised_at)}</span>
                  </div>
                  <div className="mt-1 text-xs font-medium text-ink">{titleCase(a.kind)}</div>
                  <p className="mt-0.5 text-xs leading-snug text-ink-2">{a.reason_text}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Maintenance" subtitle="Hours since service against the OEM interval">
          {!maintenance ? (
            <Empty>No maintenance record.</Empty>
          ) : (
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-ink-2">Risk</span>
                <span
                  className={
                    "rounded-full border px-2 py-0.5 text-xs font-medium " +
                    (maintenance.risk_level === "DUE"
                      ? "border-critical/40 bg-critical/10 text-critical"
                      : maintenance.risk_level === "HIGH"
                        ? "border-warning/40 bg-warning/10 text-warning"
                        : "border-hair text-ink-2")
                  }
                >
                  {maintenance.risk_level}
                </span>
              </div>
              <Row label="Hours since service" value={hours(maintenance.hours_since_service)} />
              <Row label="Interval" value={hours(maintenance.service_interval_hours)} />
              <Row label="Consumed" value={pct(maintenance.risk_ratio * 100, 0)} />
              <Row label="Burn rate" value={`${num(maintenance.engine_hours_per_day)} h/day`} />
              {maintenance.estimated_days_to_service != null && (
                <Row label="Service in" value={`${maintenance.estimated_days_to_service} days`} />
              )}
              {maintenance.recommendation && (
                <p className="border-t border-hair pt-2 text-xs leading-snug text-ink-2">{maintenance.recommendation}</p>
              )}
            </div>
          )}
        </Card>

        <Card title="Timeline" subtitle="Newest first, from the event log" bodyClassName="p-0">
          {timeline.length === 0 ? (
            <Empty>No events yet.</Empty>
          ) : (
            <ul className="max-h-[280px] divide-y divide-hair overflow-y-auto">
              {timeline.slice(0, 40).map((e) => (
                <li key={e.event_id} className="flex items-start justify-between gap-2 px-4 py-2">
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-ink">{titleCase(e.event_type)}</div>
                    <div className="text-[10px] text-ink-muted">
                      {e.source}
                      {e.actor && ` · ${e.actor}`}
                    </div>
                  </div>
                  <span className="shrink-0 text-[10px] text-ink-muted">{formatDateTime(e.occurred_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {asset.check_out_date && (
        <Card title="Current rental">
          <div className="grid grid-cols-2 gap-3 text-sm lg:grid-cols-4">
            <Row label="Checked out" value={formatDate(asset.check_out_date)} />
            <Row label="Expected back" value={formatDate(asset.expected_check_in_date)} />
            <Row label="Rental id" value={String(asset.rental_id ?? "—")} />
            <Row label="Operator" value={asset.operator_name ?? "—"} />
          </div>
        </Card>
      )}
    </div>
  );
}

function Mini({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="card p-3">
      <div className="text-[10px] font-medium uppercase tracking-wide text-ink-muted">{label}</div>
      <div className={"mt-1 text-lg font-semibold " + (tone ?? "text-ink")}>{value}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs text-ink-muted">{label}</span>
      <span className="tnum text-sm text-ink">{value}</span>
    </div>
  );
}

/** One end of a handover. Kept side by side so the comparison is the layout. */
function PhotoSet({ label, rows }: { label: string; rows: AssetPhoto[] }) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-ink">{label}</span>
        <span className="text-[11px] text-ink-muted tnum">{rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-hair px-3 py-4 text-center text-[11px] text-ink-muted">
          None recorded
        </p>
      ) : (
        <ul className="grid grid-cols-3 gap-2">
          {rows.map((p) => (
            <li key={p.photo_id}>
              {/* Opens the full-size original; the thumbnail is a crop. */}
              <a href={p.url} target="_blank" rel="noreferrer" title={p.caption ?? undefined}>
                <img
                  src={p.url}
                  alt={p.caption ?? p.original_name ?? `photo ${p.photo_id}`}
                  loading="lazy"
                  className="aspect-square w-full rounded-lg border border-hair object-cover transition-opacity hover:opacity-80"
                />
              </a>
              <p className="mt-1 truncate text-[10px] text-ink-muted" title={formatDateTime(p.taken_at)}>
                {timeAgo(p.taken_at)}
                {p.actor ? ` · ${p.actor}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
