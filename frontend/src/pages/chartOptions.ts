/**
 * Chart option builders, kept out of the page components so the pages stay
 * about layout and the option objects stay reviewable next to each other.
 *
 * Every builder declares its axes literally (rather than spreading a shared
 * axis) because ECharts' axis option is a union discriminated by `type` -- a
 * spread erases the discriminant and the option stops typechecking.
 */
import { chartTheme, type EChartsOption } from "@/components/chartTheme";
import { money, moneyShort, num, titleCase } from "@/lib/format";
import { statusColor, token, typeColor, TYPE_ORDER } from "@/lib/palette";
import type { AssetStatus, DailyUsage, Forecast, IdleCostRow, UsageGroup } from "@/lib/types";

const STATUS_ORDER: AssetStatus[] = [
  "IN_USE",
  "IDLE",
  "AVAILABLE",
  "OVERDUE",
  "UNACCOUNTED",
  "MAINTENANCE",
  "RENTED",
];

/** Fleet status counts: magnitude across a handful of categories -> ranked bars. */
export function statusOption(counts: Partial<Record<AssetStatus, number>>): EChartsOption {
  const t = chartTheme();
  const rows = STATUS_ORDER.filter((s) => (counts[s] ?? 0) > 0).map((s) => ({
    name: titleCase(s),
    value: counts[s] ?? 0,
    color: statusColor(s),
  }));

  return {
    textStyle: t.textStyle,
    grid: { left: 8, right: 44, top: 10, bottom: 8, containLabel: true },
    tooltip: { ...t.tooltip, trigger: "item", formatter: "{b}: <b>{c}</b> assets" },
    xAxis: { type: "value", show: true, axisLabel: { show: false }, splitLine: { show: false }, axisLine: { show: false } },
    yAxis: {
      type: "category",
      inverse: true,
      data: rows.map((r) => r.name),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { color: t.ink2, fontSize: 11 },
    },
    series: [
      {
        type: "bar",
        barWidth: 14,
        data: rows.map((r) => ({ value: r.value, itemStyle: { color: r.color } })),
        // 4px rounded data-end, anchored to the baseline.
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: "right", color: t.ink2, fontSize: 11 },
      },
    ],
  };
}

/** Utilisation by equipment type. One measure, one axis. */
export function utilisationByTypeOption(rows: UsageGroup[]): EChartsOption {
  const t = chartTheme();
  return {
    textStyle: t.textStyle,
    grid: { left: 8, right: 16, top: 10, bottom: 8, containLabel: true },
    tooltip: {
      ...t.tooltip,
      trigger: "item",
      formatter: (p: unknown) => {
        const d = p as { name: string; value: number; data: { engine: number; idle: number } };
        return `<b>${d.name}</b><br/>Utilisation ${d.value}%<br/>${num(d.data.engine)}h engine · ${num(d.data.idle)}h idle`;
      },
    },
    xAxis: {
      type: "category",
      data: rows.map((r) => r.key),
      axisLine: { lineStyle: { color: t.baseline } },
      axisTick: { show: false },
      // interval:0 forces every category to render (ECharts drops labels to avoid
      // overlap otherwise, which under-reports the bars); the slant is what keeps
      // five type names from colliding in a narrow card.
      axisLabel: { color: t.muted, fontSize: 10, interval: 0, hideOverlap: false, rotate: 20 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      max: 100,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11, formatter: "{value}%" },
      splitLine: { lineStyle: { color: t.gridline, width: 1 } },
    },
    series: [
      {
        type: "bar",
        barWidth: "45%",
        data: rows.map((r) => ({
          value: r.utilization_pct,
          engine: r.engine_hours,
          idle: r.idle_hours,
          itemStyle: { color: typeColor(r.key) },
        })),
        itemStyle: { borderRadius: [4, 4, 0, 0] },
      },
    ],
  };
}

/** Idle-cost leaders: the reader wants the worst offenders in order. */
export function idleCostOption(all: IdleCostRow[]): EChartsOption {
  const t = chartTheme();
  const rows = [...all].sort((a, b) => b.idle_cost - a.idle_cost).slice(0, 8).reverse();

  return {
    textStyle: t.textStyle,
    grid: { left: 8, right: 76, top: 10, bottom: 8, containLabel: true },
    tooltip: {
      ...t.tooltip,
      trigger: "item",
      formatter: (p: unknown) => {
        const d = p as { name: string; data: { value: number; idle: number; util: number } };
        return `<b>${d.name}</b><br/>${money(d.data.value)} idle cost<br/>${num(d.data.idle)}h idle · ${d.data.util}% utilised`;
      },
    },
    xAxis: { type: "value", axisLabel: { show: false }, splitLine: { show: false }, axisLine: { show: false } },
    yAxis: {
      type: "category",
      data: rows.map((r) => r.equipment_id),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { color: t.ink2, fontSize: 11 },
    },
    series: [
      {
        type: "bar",
        barWidth: 12,
        itemStyle: { borderRadius: [0, 4, 4, 0] },
        data: rows.map((r) => ({
          value: r.idle_cost,
          idle: r.idle_hours,
          util: r.utilization_pct,
          itemStyle: { color: typeColor(r.type) },
        })),
        label: {
          show: true,
          position: "right",
          color: t.ink2,
          fontSize: 11,
          formatter: (p: unknown) => moneyShort((p as { value: number }).value),
        },
      },
    ],
  };
}

/**
 * Daily engine vs idle hours. Same unit, so they stack on one axis -- never a
 * second y-scale.
 */
export function dailyUsageOption(rows: DailyUsage[]): EChartsOption {
  const t = chartTheme();
  return {
    textStyle: t.textStyle,
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
    tooltip: { ...t.tooltip, trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.baseline } } },
    legend: { ...t.legend, data: ["Engine hours", "Idle hours"] },
    xAxis: {
      type: "category",
      data: rows.map((r) => r.day.slice(5)),
      axisLine: { lineStyle: { color: t.baseline } },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: "hours",
      nameTextStyle: { color: t.muted, fontSize: 10 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.gridline, width: 1 } },
    },
    series: [
      {
        name: "Engine hours",
        type: "bar",
        stack: "hours",
        barWidth: "60%",
        data: rows.map((r) => r.engine_hours),
        itemStyle: { color: token("--series-1") },
      },
      {
        name: "Idle hours",
        type: "bar",
        stack: "hours",
        barWidth: "60%",
        data: rows.map((r) => r.idle_hours),
        // 2px surface gap keeps the boundary between stacked segments readable.
        itemStyle: {
          color: token("--series-4"),
          borderRadius: [3, 3, 0, 0],
          borderColor: t.surface,
          borderWidth: 2,
        },
      },
    ],
  };
}

/** Predicted weekly demand, one line per equipment type. */
export function forecastOption(rows: Forecast[]): EChartsOption {
  const t = chartTheme();
  const weeks = [...new Set(rows.map((r) => r.week_start))].sort();
  const types = TYPE_ORDER.filter((ty) => rows.some((r) => r.equipment_type === ty));

  return {
    textStyle: t.textStyle,
    grid: { left: 8, right: 16, top: 30, bottom: 8, containLabel: true },
    tooltip: { ...t.tooltip, trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.baseline } } },
    legend: { ...t.legend, data: [...types] },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: weeks.map((w) => w.slice(5)),
      axisLine: { lineStyle: { color: t.baseline } },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: "units",
      nameTextStyle: { color: t.muted, fontSize: 10 },
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: t.gridline, width: 1 } },
    },
    series: types.map((ty) => ({
      name: ty,
      type: "line" as const,
      smooth: true,
      symbolSize: 8,
      lineStyle: { width: 2 },
      itemStyle: { color: typeColor(ty) },
      data: weeks.map((w) => {
        const hit = rows.filter((r) => r.week_start === w && r.equipment_type === ty);
        return hit.length === 0 ? null : Number(hit.reduce((sum, r) => sum + r.predicted_demand, 0).toFixed(2));
      }),
    })),
  };
}

/** Utilisation by site, ranked. Single sequential hue -- rank is not identity. */
export function utilisationBySiteOption(all: UsageGroup[], nameOf: (key: string) => string): EChartsOption {
  const t = chartTheme();
  const rows = [...all].sort((a, b) => b.utilization_pct - a.utilization_pct);

  return {
    textStyle: t.textStyle,
    grid: { left: 8, right: 56, top: 10, bottom: 8, containLabel: true },
    tooltip: {
      ...t.tooltip,
      trigger: "item",
      formatter: (p: unknown) => {
        const d = p as { name: string; value: number; data: { engine: number; idle: number } };
        return `<b>${d.name}</b><br/>${d.value}% utilised<br/>${num(d.data.engine)}h engine · ${num(d.data.idle)}h idle`;
      },
    },
    xAxis: { type: "value", max: 100, axisLabel: { show: false }, splitLine: { show: false }, axisLine: { show: false } },
    yAxis: {
      type: "category",
      inverse: true,
      data: rows.map((r) => nameOf(r.key)),
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { color: t.ink2, fontSize: 11 },
    },
    series: [
      {
        type: "bar",
        barWidth: 12,
        // One measure ranked by magnitude: a single hue, because rank is not identity.
        itemStyle: { borderRadius: [0, 4, 4, 0], color: token("--series-1") },
        data: rows.map((r) => ({ value: r.utilization_pct, engine: r.engine_hours, idle: r.idle_hours })),
        label: {
          show: true,
          position: "right",
          color: t.ink2,
          fontSize: 11,
          formatter: (p: unknown) => `${(p as { value: number }).value}%`,
        },
      },
    ],
  };
}
