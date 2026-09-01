/**
 * Small shared pieces. Status and severity always render an icon and a label
 * beside the colour, so identity never rests on hue alone.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { AssetStatus, Severity } from "@/lib/types";
import {
  SEVERITY_CLASS,
  SEVERITY_ICON,
  STATUS_CLASS,
  STATUS_ICON,
} from "@/lib/palette";
import { titleCase } from "@/lib/format";

export function StatusChip({ status, className = "" }: { status: AssetStatus; className?: string }) {
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap " +
        (STATUS_CLASS[status] ?? STATUS_CLASS.AVAILABLE) +
        " " +
        className
      }
    >
      <span aria-hidden>{STATUS_ICON[status] ?? "○"}</span>
      {titleCase(status)}
    </span>
  );
}

export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap " +
        (SEVERITY_CLASS[severity] ?? SEVERITY_CLASS.INFO)
      }
    >
      <span aria-hidden>{SEVERITY_ICON[severity] ?? "ℹ"}</span>
      {severity}
    </span>
  );
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  bodyClassName = "p-4",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={"card flex flex-col overflow-hidden " + className}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-hair px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={"min-h-0 flex-1 " + bodyClassName}>{children}</div>
    </section>
  );
}

/**
 * A stat tile is the right form for a single headline number -- a chart here
 * would be decoration. The value keeps proportional figures; only aligned
 * columns get tabular ones.
 */
export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
  to,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "neutral" | "good" | "warning" | "serious" | "critical";
  to?: string;
}) {
  const toneClass = {
    neutral: "text-ink",
    good: "text-good",
    warning: "text-warning",
    serious: "text-serious",
    critical: "text-critical",
  }[tone];

  const body = (
    <>
      <div className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</div>
      <div className={"mt-1.5 text-2xl font-semibold leading-none " + toneClass}>{value}</div>
      {hint && <div className="mt-1.5 text-xs text-ink-2">{hint}</div>}
    </>
  );

  return to ? (
    <Link to={to} className="card block p-4 transition-colors hover:border-ink-muted/40">
      {body}
    </Link>
  ) : (
    <div className="card p-4">{body}</div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 p-6 text-sm text-ink-muted">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink-muted/30 border-t-ink-muted" />
      {label}
    </div>
  );
}

export function ErrorNote({ error, className = "" }: { error: unknown; className?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className={"rounded-lg border border-critical/40 bg-critical/10 p-3 text-sm text-critical " + className}>
      <span className="mr-1.5" aria-hidden>
        ⬤
      </span>
      {message}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="p-6 text-center text-sm text-ink-muted">{children}</div>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="font-medium uppercase tracking-wide text-ink-muted">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "rounded-lg border border-hair bg-raised px-2.5 py-1.5 text-sm text-ink outline-none " +
  "focus:border-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)] placeholder:text-ink-muted";

export const buttonClass =
  "inline-flex items-center gap-1.5 rounded-lg border border-hair bg-raised px-3 py-1.5 text-sm " +
  "font-medium text-ink transition-colors hover:border-ink-muted/50 disabled:opacity-50";

export const primaryButtonClass =
  "inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium " +
  "text-white transition-opacity hover:opacity-90 disabled:opacity-50";
