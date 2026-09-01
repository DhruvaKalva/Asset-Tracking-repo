/**
 * Analytics: demand forecast, anomalies, shortages, cost recommendations.
 *
 * The forecast chart reports which model answered plus its backtested MAPE --
 * the backend degrades
 * from Holt-Winters to exponential smoothing to a moving average depending on how
 * much history exists, and hiding that would overstate the prediction.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { EChart } from "@/components/EChart";
import { forecastOption, utilisationBySiteOption } from "@/pages/chartOptions";
import { Card, Empty, ErrorNote, SeverityChip, Spinner, buttonClass, inputClass } from "@/components/primitives";
import {
  useAnomalies,
  useForecast,
  useMaintenance,
  useRecommendations,
  useRunJob,
  useShortages,
  useSites,
  useUsage,
} from "@/hooks/queries";
import { formatDate, money, moneyShort, num, pct, titleCase } from "@/lib/format";

export default function AnalyticsPage() {
  const [siteId, setSiteId] = useState("");
  const sites = useSites();
  const forecast = useForecast(4);
  const shortages = useShortages();
  const anomalies = useAnomalies();
  const recs = useRecommendations();
  const maintenance = useMaintenance();
  const usageBySite = useUsage("site");
  const runJob = useRunJob();

  const forecastChart = useMemo(
    () => forecastOption((forecast.data ?? []).filter((f) => (siteId ? f.site_id === siteId : true))),
    [forecast.data, siteId],
  );

  const siteChart = useMemo(
    () =>
      utilisationBySiteOption(
        usageBySite.data ?? [],
        (key) => sites.data?.find((s) => s.site_id === key)?.name ?? key,
      ),
    [usageBySite.data, sites.data],
  );

  const flagged = useMemo(() => (anomalies.data ?? []).filter((a) => a.is_anomaly), [anomalies.data]);
  const dueSoon = useMemo(
    () => (maintenance.data ?? []).filter((m) => m.risk_level !== "OK").sort((a, b) => b.risk_ratio - a.risk_ratio),
    [maintenance.data],
  );
  const sortedRecs = useMemo(
    () => [...(recs.data ?? [])].sort((a, b) => b.estimated_saving - a.estimated_saving),
    [recs.data],
  );
  const totalSaving = sortedRecs.reduce((s, r) => s + r.estimated_saving, 0);

  return (
    <div className="space-y-4 p-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Analytics</h1>
          <p className="text-sm text-ink-muted">Demand forecast, anomaly detection and cost recovery</p>
        </div>
        <div className="flex items-center gap-2">
          <button className={buttonClass} onClick={() => runJob.mutate("anomaly")} disabled={runJob.isPending}>
            ↻ Anomaly scan
          </button>
          <button className={buttonClass} onClick={() => runJob.mutate("forecast")} disabled={runJob.isPending}>
            ↻ Re-forecast
          </button>
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card
          title="Demand forecast, next 4 weeks"
          subtitle="Predicted rentals per week by equipment type"
          actions={
            <select className={inputClass} value={siteId} onChange={(e) => setSiteId(e.target.value)}>
              <option value="">All sites</option>
              {(sites.data ?? []).map((s) => (
                <option key={s.site_id} value={s.site_id}>
                  {s.name}
                </option>
              ))}
            </select>
          }
        >
          {forecast.isLoading ? (
            <Spinner />
          ) : forecast.isError ? (
            <ErrorNote error={forecast.error} />
          ) : (
            <>
              <EChart option={forecastChart} height={260} />
              <ModelNote rows={(forecast.data ?? []).filter((f) => (siteId ? f.site_id === siteId : true))} />
            </>
          )}
        </Card>

        <Card title="Utilisation by site" subtitle="Engine hours as a share of logged hours">
          {usageBySite.isLoading ? <Spinner /> : <EChart option={siteChart} height={260} />}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Predicted shortages (${shortages.data?.length ?? 0})`} subtitle="Demand above what is free now" bodyClassName="p-0">
          {shortages.isLoading ? (
            <Spinner />
          ) : (shortages.data ?? []).length === 0 ? (
            <Empty>No shortages predicted.</Empty>
          ) : (
            <ul className="divide-y divide-hair">
              {(shortages.data ?? []).map((s, i) => (
                <li key={`${s.site_id}-${s.equipment_type}-${i}`} className="px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-ink">
                      {s.equipment_type} · {sites.data?.find((x) => x.site_id === s.site_id)?.name ?? s.site_id}
                    </span>
                    <span className="tnum text-xs font-semibold text-warning">short {num(s.shortfall)}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-ink-2">{s.recommendation}</p>
                  <p className="mt-0.5 text-[10px] text-ink-muted">
                    week of {formatDate(s.week_start)} · {s.available_now} free now · {s.confidence}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={`Anomalies (${flagged.length})`} subtitle="Rules first, IsolationForest second, max severity wins" bodyClassName="p-0">
          {anomalies.isLoading ? (
            <Spinner />
          ) : flagged.length === 0 ? (
            <Empty>Nothing anomalous today.</Empty>
          ) : (
            <ul className="max-h-[380px] divide-y divide-hair overflow-y-auto">
              {flagged.map((a) => (
                <li key={`${a.equipment_id}-${a.day}`} className="px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <Link to={`/assets/${a.equipment_id}`} className="text-sm font-medium text-ink hover:text-[var(--accent)]">
                      {a.equipment_id}
                    </Link>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-ink-muted tnum">ML {a.ml_score.toFixed(2)}</span>
                      <SeverityChip severity={a.final_severity} />
                    </div>
                  </div>
                  {(a.reasons.rules ?? []).map((r, i) => (
                    <p key={i} className="mt-1 text-xs leading-snug text-ink-2">
                      <span className="font-medium text-ink-2">{titleCase(r.kind)}:</span> {r.reason}
                    </p>
                  ))}
                  {a.reasons.ml?.flagged && (
                    <p className="mt-1 text-[11px] leading-snug text-ink-muted">{a.reasons.ml.explanation}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title={`Recommendations (${sortedRecs.length})`}
          subtitle={`${moneyShort(totalSaving)} identified across the fleet`}
          bodyClassName="p-0"
        >
          {recs.isLoading ? (
            <Spinner />
          ) : sortedRecs.length === 0 ? (
            <Empty>Nothing to recommend.</Empty>
          ) : (
            <ul className="divide-y divide-hair">
              {sortedRecs.map((r, i) => (
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
                    <div className="tnum text-sm font-semibold text-good">{money(r.estimated_saving)}</div>
                    <div className="text-[10px] uppercase tracking-wide text-ink-muted">saving</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title={`Service due (${dueSoon.length})`} subtitle="Against the OEM interval" bodyClassName="p-0">
          {maintenance.isLoading ? (
            <Spinner />
          ) : dueSoon.length === 0 ? (
            <Empty>Nothing due.</Empty>
          ) : (
            <ul className="max-h-[340px] divide-y divide-hair overflow-y-auto">
              {dueSoon.map((m) => (
                <li key={m.equipment_id} className="px-4 py-3">
                  <div className="flex items-center justify-between gap-2">
                    <Link to={`/assets/${m.equipment_id}`} className="text-sm font-medium text-ink hover:text-[var(--accent)]">
                      {m.equipment_id}
                    </Link>
                    <span
                      className={
                        "rounded-full border px-2 py-0.5 text-[10px] font-medium " +
                        (m.risk_level === "DUE"
                          ? "border-critical/40 bg-critical/10 text-critical"
                          : "border-warning/40 bg-warning/10 text-warning")
                      }
                    >
                      {m.risk_level}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-muted/20">
                    <div
                      className={"h-full rounded-full " + (m.risk_level === "DUE" ? "bg-critical" : "bg-warning")}
                      style={{ width: `${Math.min(100, m.risk_ratio * 100)}%` }}
                    />
                  </div>
                  <p className="mt-1 text-[11px] text-ink-muted tnum">
                    {pct(m.risk_ratio * 100, 0)} of interval
                    {m.estimated_days_to_service != null && ` · service in ${m.estimated_days_to_service}d`}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

/** Names the model that answered and its backtested error, per the API contract. */
function ModelNote({ rows }: { rows: { model_version: string; mape: number | null }[] }) {
  if (rows.length === 0) return null;
  const models = [...new Set(rows.map((r) => r.model_version.split("|")[0]))];
  const mapes = rows.map((r) => r.mape).filter((m): m is number => m != null);
  const avg = mapes.length ? mapes.reduce((a, b) => a + b, 0) / mapes.length : null;
  return (
    <p className="mt-2 border-t border-hair pt-2 text-[11px] leading-snug text-ink-muted">
      Model: {models.join(", ")} ·{" "}
      {avg != null ? (
        <>mean backtested MAPE {avg.toFixed(1)}%</>
      ) : (
        <>error not reported — too little history to claim one</>
      )}
    </p>
  );
}
