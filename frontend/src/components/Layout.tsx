/**
 * App shell. Mounts the single SSE connection for the whole app, so every page
 * reads live data from one socket instead of opening its own.
 */
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useLive, useLiveStream, toastKey } from "@/hooks/useLiveStream";
import { useAuth } from "@/store/auth";
import { useTheme } from "@/store/ui";
import { useOverview } from "@/hooks/queries";
import { SeverityChip } from "@/components/primitives";
import { Mira } from "@/components/Mira";
import { timeAgo } from "@/lib/format";

const NAV = [
  { to: "/", label: "Overview", icon: "▤", end: true },
  { to: "/map", label: "Live Map", icon: "◎" },
  { to: "/assets", label: "Assets", icon: "▦", end: true },
  { to: "/alerts", label: "Alerts", icon: "⚠" },
  { to: "/analytics", label: "Analytics", icon: "◫" },
  { to: "/scan", label: "Check In/Out", icon: "⧉" },
  { to: "/assets/new", label: "Add Asset", icon: "＋" },
];

export function Layout() {
  useLiveStream();

  const status = useLive((s) => s.status);
  const lastFrameAt = useLive((s) => s.lastFrameAt);
  const toasts = useLive((s) => s.toasts);
  const dismissToast = useLive((s) => s.dismissToast);

  const { theme, toggle } = useTheme();
  const { user, signOut } = useAuth();
  const { data: overview } = useOverview();
  const navigate = useNavigate();

  const openAlerts = overview?.open_alerts ?? 0;

  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-hair bg-surface">
        <div className="border-b border-hair px-4 py-4">
          <div className="text-sm font-semibold leading-tight text-ink">Smart Rental</div>
          <div className="text-xs text-ink-muted">Tracking System</div>
        </div>

        <nav className="flex-1 space-y-0.5 p-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                "flex items-center justify-between rounded-lg px-3 py-2 text-sm transition-colors " +
                (isActive
                  ? "bg-[var(--accent)]/12 font-medium text-[var(--accent)]"
                  : "text-ink-2 hover:bg-ink-muted/10 hover:text-ink")
              }
            >
              <span className="flex items-center gap-2.5">
                <span aria-hidden className="w-4 text-center opacity-80">
                  {item.icon}
                </span>
                {item.label}
              </span>
              {item.to === "/alerts" && openAlerts > 0 && (
                <span className="rounded-full bg-critical/15 px-1.5 py-0.5 text-[10px] font-semibold text-critical tnum">
                  {openAlerts}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-2 border-t border-hair p-3">
          <ConnectionPill status={status} lastFrameAt={lastFrameAt} />
          <button
            onClick={toggle}
            className="w-full rounded-lg border border-hair px-3 py-1.5 text-xs text-ink-2 hover:text-ink"
          >
            {theme === "dark" ? "☀ Light mode" : "☾ Dark mode"}
          </button>
          <div className="flex items-center justify-between px-1 pt-1">
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-ink">{user?.name}</div>
              <div className="text-[10px] uppercase tracking-wide text-ink-muted">{user?.role}</div>
            </div>
            <button onClick={signOut} className="text-xs text-ink-muted hover:text-critical" title="Sign out">
              ⏻
            </button>
          </div>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>

      {/* Alert toasts, pushed straight off the SSE stream. Stacked above the
          Mira orb rather than under it, so neither one buries the other. */}
      <div className="pointer-events-none fixed bottom-4 right-24 z-40 flex w-80 flex-col gap-2">
        {toasts.map((t, i) => (
          <button
            key={toastKey(t, i)}
            onClick={() => {
              dismissToast(i);
              navigate(`/assets/${t.equipment_id}`);
            }}
            className="card pointer-events-auto animate-[fadeIn_.2s_ease-out] p-3 text-left shadow-lg hover:border-ink-muted/40"
          >
            <div className="flex items-center justify-between gap-2">
              <SeverityChip severity={t.severity} />
              <span className="text-xs font-medium text-ink">{t.equipment_id}</span>
            </div>
            <p className="mt-1.5 text-xs leading-snug text-ink-2">{t.reason_text}</p>
          </button>
        ))}
      </div>

      <Mira />
    </div>
  );
}

function ConnectionPill({ status, lastFrameAt }: { status: string; lastFrameAt: number | null }) {
  const map = {
    live: { dot: "bg-good", label: "Live", cls: "text-good" },
    connecting: { dot: "bg-warning animate-pulse", label: "Connecting", cls: "text-warning" },
    offline: { dot: "bg-critical", label: "Offline", cls: "text-critical" },
  }[status] ?? { dot: "bg-ink-muted", label: status, cls: "text-ink-muted" };

  return (
    <div className="flex items-center justify-between rounded-lg border border-hair px-2.5 py-1.5">
      <span className={"flex items-center gap-1.5 text-xs font-medium " + map.cls}>
        <span className={"h-1.5 w-1.5 rounded-full " + map.dot} />
        {map.label}
      </span>
      <span className="text-[10px] text-ink-muted">
        {lastFrameAt ? timeAgo(new Date(lastFrameAt).toISOString()) : "--"}
      </span>
    </div>
  );
}
