/**
 * Thin ECharts binding.
 *
 * Written directly against `echarts` rather than a wrapper package so there is
 * no peer-dependency lag behind React. Only the modules actually used are
 * imported, which keeps the chart bundle well under the full build.
 *
 * `chartTheme()` returns the chart chrome the design method asks for -- recessive
 * hairline grid, muted axis ink, tooltips styled to the app surface -- as concrete
 * fragments a chart spreads into its own option. Axes are deliberately NOT part
 * of it: `EChartsOption["xAxis"]` is a union across axis types, and spreading a
 * union loses the discriminant, so each chart declares its axes literally and
 * pulls only colours from `theme.ink`.
 */
import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
// ECharts 6 moved grid.containLabel behind an opt-in feature. Without it the
// grid ignores label extents and long axis labels get clipped.
import { LegacyGridContainLabel } from "echarts/features";
import type { EChartsOption } from "echarts";
import { useTheme } from "@/store/ui";

// Only the pieces the charts here actually use: bar, line, grid, legend, tooltip.
echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
  LegacyGridContainLabel,
]);

export function EChart({
  option,
  height = 280,
  className = "",
  onEvents,
}: {
  option: EChartsOption;
  height?: number | string;
  className?: string;
  onEvents?: Record<string, (params: unknown) => void>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const theme = useTheme((s) => s.theme);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);

    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
    // Re-init on theme change so the canvas picks up the new token values.
  }, [theme]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    // notMerge:true — a filtered chart must drop removed series, not keep ghosts.
    chart.setOption(option, { notMerge: true });
  }, [option, theme]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !onEvents) return;
    for (const [name, handler] of Object.entries(onEvents)) {
      chart.off(name);
      chart.on(name, handler);
    }
    return () => {
      for (const name of Object.keys(onEvents)) chart.off(name);
    };
  }, [onEvents, theme]);

  return <div ref={ref} className={className} style={{ height, width: "100%" }} />;
}
