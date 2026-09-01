/**
 * Chart chrome, read fresh from the CSS tokens so it follows the active theme.
 *
 * Kept out of EChart.tsx because that file must export only a component for
 * React Fast Refresh to work. Return type is inferred (not annotated as
 * EChartsOption) so each fragment stays concrete and spreadable -- see the note
 * in chartOptions.ts about axis unions.
 */
import type { EChartsOption } from "echarts";
import { token } from "@/lib/palette";

const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

export function chartTheme() {
  const ink = token("--text-primary");
  const ink2 = token("--text-secondary");
  const muted = token("--text-muted");
  const gridline = token("--gridline");
  const surface = token("--surface-1");
  const baseline = token("--baseline");

  return {
    ink,
    ink2,
    muted,
    gridline,
    surface,
    baseline,

    textStyle: { fontFamily: FONT, color: ink2 },
    grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },

    tooltip: {
      backgroundColor: surface,
      borderColor: baseline,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: ink, fontSize: 12 },
      extraCssText: "box-shadow: 0 8px 28px rgba(0,0,0,0.28); border-radius: 8px;",
    },

    legend: {
      type: "scroll" as const,
      top: 0,
      icon: "roundRect",
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 14,
      // Legend text wears text ink, never the series colour.
      textStyle: { color: ink2, fontSize: 11 },
      inactiveColor: muted,
    },
  };
}

export type { EChartsOption };
