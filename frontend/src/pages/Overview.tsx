/**
 * Fleet overview.
 *
 * Chart forms follow the data's job: single headline numbers are stat tiles (a
 * chart there would be decoration), fleet status is a bar chart of counts rather
 * than a donut (comparing magnitudes across categories), and idle cost is a
 * ranked horizontal bar because the reader wants the worst offenders in order.
 */
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { EChart } from "@/components/EChart";
import { Card, ErrorNote, SeverityChip, Spinner, StatTile, Empty } from "@/components/primitives";
import { idleCostOption, statusOption, utilisationByTypeOption } from "@/pages/chartOptions";
import { useIdleCost, useOverview, useRecommendations, useUsage } from "@/hooks/queries";
import { useLive } from "@/hooks/useLiveStream";
import { moneyShort, num, pct, timeAgo, titleCase } from "@/lib/format";

export default function Overview() {
  const overview = useOverview();
  const idleCost = useIdleCost(30);
  const usageByType = useUsage("type");
  const recs = useRecommendations();
  const recent = useLive((s) => s.recent);

  const statusChart = useMemo(() => statusOption(overview.data?.status_counts ?? {}), [overview.data]);
  const utilChart = useMemo(() => utilisationByTypeOption(usageByType.data ?? []), [usageByType.data]);
  const idleChart = useMemo(() => idleCostOption(idleCost.data ?? []), [idleCost.data]);

  if (overview.isLoading) return <Spinner label="Loading fleet overview" />;
  if (overview.isError) return <div className="p-6"><ErrorNote error={overview.error} /></div>;

  const o = overview.data!;
  const topRecs = [...(recs.data ?? [])].sort((a, b) => b.estimated_saving - a.estimated_saving).slice(0, 5);

  return (
    <div className="space-y-4 p-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Fleet Overview</h1>
          <p className="text-sm text-ink-muted">
            {o.total_assets} assets · {o.on_rent} on rent · updated {timeAgo(o.generated_at)}
          </p>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <StatTile label="On rent" value={o.on_rent} hint={`of ${o.total_assets} assets`} to="/assets?status=IN_USE" />
        <StatTile
          label="Utilisation"
          value={pct(o.fleet.utilization_pct)}
          hint={`${num(o.fleet.engine_hours, 0)}h engine / ${num(o.fleet.idle_hours, 0)}h idle`}
          tone={o.fleet.utilization_pct >= 70 ? "good" : o.fleet.utilization_pct >= 50 ? "warning" : "serious"}
        />
        <StatTile label="Overdue" value={o.overdue} hint="past expected return" tone={o.overdue > 0 ? "serious" : "neutral"} to="/assets" />
        <StatTile
          label="Unaccounted"
          value={o.unaccounted}
          hint="no site or stale ping"
          tone={o.unaccounted > 0 ? "critical" : "neutral"}
        />
        <StatTile
          label="Open alerts"
          value={o.open_alerts}
          hint={`${o.critical_alerts} critical`}
          tone={o.critical_alerts > 0 ? "critical" : o.open_alerts > 0 ? "warning" : "good"}
          to="/alerts"
        />
        <StatTile
          label="Identified savings"
          value={moneyShort(o.savings.identified_savings)}
          hint={`${o.savings.open_recommendations} recommendations`}
          tone="good"
          to="/analytics"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Fleet status" subtitle="Derived from rental, hours and last ping">
          <EChart option={statusChart} height={220} />
        </Card>

        <Card title="Utilisation by equipment type" subtitle="Engine hours as a share of total logged hours">
          {usageByType.isLoading ? <Spinner /> : <EChart option={utilChart} height={220} />}
        </Card>

        <Card title="Idle cost leaders" subtitle="Last 30 days, rate × idle hours">
          {idleCost.isLoading ? <Spinner /> : <EChart option={idleChart} height={220} />}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Top recommendations"
          subtitle="Ranked by rupee impact"
          actions={
            <Link to="/analytics" className="text-xs text-[var(--accent)] hover:underline">
              View all →
            </Link>
          }
          bodyClassName="p-0"
        >
          {recs.isLoading ? (
            <Spinner />
          ) : topRecs.length === 0 ? (
            <Empty>No open recommendations.</Empty>
          ) : (
            <ul className="divide-y divide-hair">
              {topRecs.map((r, i) => (
                <li key={`${r.kind}-${r.equipment_id}-${i}`} className="flex items-start gap-3 px-4 py-3">
                  <SeverityChip severity={r.severity} />
                  <div className="min-w-0 flex-1">
                    <Link to={`/assets/${r.equipment_id}`} className="text-sm font-medium text-ink hover:text-[var(--accent)]">
                      {r.equipment_id}
                    </Link>
                    <span className="ml-2 text-xs text-ink-muted">{titleCase(r.kind)}</span>
                    <p className="mt-0.5 text-xs leading-snug text-ink-2">{r.detail}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-sm font-semibold text-good tnum">{moneyShort(r.estimated_saving)}</div>
                    <div className="text-[10px] uppercase tracking-wide text-ink-muted">saving</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Live activity" subtitle="Straight off the event stream" bodyClassName="p-0">
          {recent.length === 0 ? (
            <Empty>Waiting for the first frame…</Empty>
          ) : (
            <ul className="max-h-[300px] divide-y divide-hair overflow-y-auto">
              {recent.slice(0, 18).map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-2 px-4 py-2 text-xs">
                  <Link to={`/assets/${e.equipment_id}`} className="font-medium text-ink hover:text-[var(--accent)]">
                    {e.equipment_id}
                  </Link>
                  <span className="truncate text-ink-muted">{titleCase(e.event_type)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
