/** Display helpers. The fleet is priced in rupees, matching the seed data. */

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

export const money = (n: number | null | undefined) => (n == null ? "--" : inr.format(n));

/** Compact rupee for stat tiles: ₹5.7L / ₹33.3L / ₹1.2Cr. */
export function moneyShort(n: number | null | undefined): string {
  if (n == null) return "--";
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  if (abs >= 1e3) return `₹${(n / 1e3).toFixed(1)}k`;
  return inr.format(n);
}

export const num = (n: number | null | undefined, digits = 1) =>
  n == null ? "--" : n.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const pct = (n: number | null | undefined, digits = 1) =>
  n == null ? "--" : `${n.toFixed(digits)}%`;

export const hours = (n: number | null | undefined) => (n == null ? "--" : `${num(n)} h`);

/**
 * The backend serialises naive UTC datetimes for most rows (no trailing Z) but
 * tz-aware ones for `generated_at`. Treat a bare timestamp as UTC so "last seen"
 * is not silently shifted by the viewer's offset.
 */
export function parseUtc(value: string | null | undefined): Date | null {
  if (!value) return null;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value);
  const d = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatTime(value: string | null | undefined): string {
  const d = parseUtc(value);
  return d ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--";
}

export function formatDateTime(value: string | null | undefined): string {
  const d = parseUtc(value);
  return d
    ? d.toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "--";
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "--";
  const d = new Date(`${value}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleDateString([], { day: "2-digit", month: "short", year: "numeric" });
}

export function timeAgo(value: string | null | undefined): string {
  const d = parseUtc(value);
  if (!d) return "never";
  const secs = Math.floor((Date.now() - d.getTime()) / 1000);
  if (secs < 0) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/** "in 4 days" / "3 days overdue" -- the sign is what the reader cares about. */
export function dueLabel(days: number | null | undefined): string {
  if (days == null) return "--";
  if (days < 0) return `${Math.abs(days)}d overdue`;
  if (days === 0) return "due today";
  return `in ${days}d`;
}

export const titleCase = (s: string) =>
  s.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
