/**
 * Alert inbox. Every alert the backend raises ships a human-readable reason and
 * the evidence behind it, so the row shows both rather than just a code.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Card, Empty, ErrorNote, SeverityChip, Spinner, buttonClass, inputClass } from "@/components/primitives";
import { useAcknowledgeAlert, useAlerts, useRunJob } from "@/hooks/queries";
import { useAuth } from "@/store/auth";
import { formatDateTime, num, timeAgo, titleCase } from "@/lib/format";
import { SEVERITY_RANK } from "@/lib/palette";
import type { Severity } from "@/lib/types";

const SEVERITIES: Severity[] = ["CRITICAL", "HIGH", "WARN", "INFO"];

export default function AlertsPage() {
  const [severity, setSeverity] = useState("");
  const [kind, setKind] = useState("");
  const [unresolved, setUnresolved] = useState(true);

  const { data, isLoading, isError, error } = useAlerts({
    severity: severity || undefined,
    kind: kind || undefined,
    unresolved,
  });
  const acknowledge = useAcknowledgeAlert();
  const runJob = useRunJob();
  const user = useAuth((s) => s.user);

  const kinds = useMemo(() => [...new Set((data ?? []).map((a) => a.kind))].sort(), [data]);

  const sorted = useMemo(
    () =>
      [...(data ?? [])].sort(
        (a, b) =>
          SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] ||
          new Date(b.raised_at).getTime() - new Date(a.raised_at).getTime(),
      ),
    [data],
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-hair bg-surface px-5 py-3">
        <div className="mr-2">
          <h1 className="text-base font-semibold text-ink">Alerts</h1>
          <p className="text-xs text-ink-muted">{sorted.length} shown</p>
        </div>
        <select className={inputClass} value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">All severities</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All kinds</option>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {titleCase(k)}
            </option>
          ))}
        </select>
        <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-hair px-2.5 py-1.5 text-sm text-ink-2">
          <input
            type="checkbox"
            className="accent-[var(--accent)]"
            checked={unresolved}
            onChange={(e) => setUnresolved(e.target.checked)}
          />
          Unresolved only
        </label>
        <button
          className={buttonClass + " ml-auto"}
          onClick={() => runJob.mutate("overdue")}
          disabled={runJob.isPending}
        >
          {runJob.isPending ? "Scanning…" : "↻ Run overdue scan"}
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {isLoading ? (
          <Spinner label="Loading alerts" />
        ) : isError ? (
          <ErrorNote error={error} />
        ) : sorted.length === 0 ? (
          <Card>
            <Empty>Nothing open. The fleet is clean.</Empty>
          </Card>
        ) : (
          <ul className="space-y-2">
            {sorted.map((a) => (
              <li key={a.alert_id} className="card p-4">
                <div className="flex flex-wrap items-start gap-3">
                  <SeverityChip severity={a.severity} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        to={`/assets/${a.equipment_id}`}
                        className="text-sm font-semibold text-ink hover:text-[var(--accent)]"
                      >
                        {a.equipment_id}
                      </Link>
                      <span className="text-xs font-medium text-ink-2">{titleCase(a.kind)}</span>
                      <span className="text-[11px] text-ink-muted">
                        {formatDateTime(a.raised_at)} · {timeAgo(a.raised_at)}
                      </span>
                      {a.acknowledged_at && (
                        <span className="rounded-full border border-hair px-2 py-0.5 text-[10px] text-ink-muted">
                          ack {timeAgo(a.acknowledged_at)}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-sm leading-snug text-ink-2">{a.reason_text}</p>
                    <Evidence evidence={a.evidence} />
                  </div>
                  {!a.acknowledged_at && (
                    <button
                      className={buttonClass}
                      disabled={acknowledge.isPending}
                      onClick={() => acknowledge.mutate({ alertId: a.alert_id, actor: user?.name })}
                    >
                      ✓ Acknowledge
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function formatEvidence(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return num(v, 2);
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}

/** The evidence dict is free-form; render whatever the rule attached. */
function Evidence({ evidence }: { evidence: Record<string, unknown> }) {
  const entries = Object.entries(evidence ?? {}).filter(([k]) => k !== "detector");
  if (entries.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {entries.map(([k, v]) => (
        <span key={k} className="rounded border border-hair px-1.5 py-0.5 text-[11px] text-ink-muted">
          {titleCase(k)}:{" "}
          <span className="tnum font-medium text-ink-2">{formatEvidence(v)}</span>
        </span>
      ))}
    </div>
  );
}
