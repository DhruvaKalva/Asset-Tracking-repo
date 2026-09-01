/**
 * Colour roles.
 *
 * Two rules from the data-viz method are load-bearing here:
 *  1. Categorical hues are assigned in fixed slot order and keyed by *entity*
 *     (equipment type), so filtering the fleet never repaints the survivors.
 *  2. Status colours are reserved -- they never double as a series colour, and
 *     they always ship beside a text label, never as colour alone.
 */
import type { AssetStatus, Severity } from "./types";

/** Reads a token so charts follow the active theme. */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export const SERIES_TOKENS = [
  "--series-1",
  "--series-2",
  "--series-3",
  "--series-4",
  "--series-5",
  "--series-6",
  "--series-7",
  "--series-8",
] as const;

/**
 * Stable slot per equipment type. The order is the fleet's own type order, so a
 * type keeps its hue across every chart on every page. A 9th type folds into the
 * last slot rather than inventing a hue -- the fleet has five.
 */
export const TYPE_ORDER = ["Excavator", "Bulldozer", "Crane", "Grader", "Loader"] as const;

export function typeColor(type: string, known: string[] = [...TYPE_ORDER]): string {
  const idx = known.indexOf(type);
  const slot = idx >= 0 ? idx : known.length;
  return token(SERIES_TOKENS[Math.min(slot, SERIES_TOKENS.length - 1)]);
}

type StatusRole = "good" | "warning" | "serious" | "critical" | "neutral";

const STATUS_ROLE: Record<AssetStatus, StatusRole> = {
  IN_USE: "good",
  AVAILABLE: "neutral",
  RENTED: "neutral",
  MAINTENANCE: "neutral",
  IDLE: "warning",
  OVERDUE: "serious",
  UNACCOUNTED: "critical",
};

const ROLE_TOKEN: Record<StatusRole, string> = {
  good: "--status-good",
  warning: "--status-warning",
  serious: "--status-serious",
  critical: "--status-critical",
  neutral: "--text-muted",
};

/** Literal hex, for canvas/WebGL consumers (MapLibre, ECharts) that can't read vars. */
export function statusColor(status: AssetStatus): string {
  return token(ROLE_TOKEN[STATUS_ROLE[status] ?? "neutral"]);
}

/** Tailwind classes for chips. Colour never travels without the label beside it. */
export const STATUS_CLASS: Record<AssetStatus, string> = {
  IN_USE: "text-good border-good/40 bg-good/10",
  AVAILABLE: "text-ink-2 border-hair bg-ink-muted/10",
  RENTED: "text-ink-2 border-hair bg-ink-muted/10",
  MAINTENANCE: "text-ink-2 border-hair bg-ink-muted/10",
  IDLE: "text-warning border-warning/40 bg-warning/10",
  OVERDUE: "text-serious border-serious/40 bg-serious/10",
  UNACCOUNTED: "text-critical border-critical/40 bg-critical/10",
};

export const SEVERITY_CLASS: Record<Severity, string> = {
  INFO: "text-ink-2 border-hair bg-ink-muted/10",
  WARN: "text-warning border-warning/40 bg-warning/10",
  HIGH: "text-serious border-serious/40 bg-serious/10",
  CRITICAL: "text-critical border-critical/40 bg-critical/10",
};

/** Icon glyph paired with every status/severity colour (the CVD mitigation). */
export const STATUS_ICON: Record<AssetStatus, string> = {
  IN_USE: "▶",
  AVAILABLE: "○",
  RENTED: "○",
  MAINTENANCE: "⚙",
  IDLE: "⏸",
  OVERDUE: "⏱",
  UNACCOUNTED: "⚠",
};

export const SEVERITY_ICON: Record<Severity, string> = {
  INFO: "ℹ",
  WARN: "⚠",
  HIGH: "▲",
  CRITICAL: "⬤",
};

export const SEVERITY_RANK: Record<Severity, number> = { INFO: 0, WARN: 1, HIGH: 2, CRITICAL: 3 };
