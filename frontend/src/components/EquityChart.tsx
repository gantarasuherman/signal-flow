"use client";

import { AreaSeries, ColorType, createChart, LineStyle, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { dayMonthWIB, dateTimeWIB } from "@/lib/format";
import { readPalette, useTheme } from "@/lib/theme";
import type { EquityPoint } from "@/lib/types";

/** Kurva modal (100 = modal awal) dari simulasi risiko % per sinyal. */
export default function EquityChart({ points, splitTime }: { points: EquityPoint[]; splitTime?: number }) {
  const container = useRef<HTMLDivElement>(null);
  const { resolved } = useTheme();

  useEffect(() => {
    const el = container.current;
    if (!el || points.length < 2) return;
    const C = readPalette();
    const final = points.at(-1)!.equity;
    const color = final >= 100 ? C.up : C.down;
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: C.text, fontSize: 10 },
      grid: { vertLines: { visible: false }, horzLines: { color: C.grid } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, tickMarkFormatter: (t: number) => dayMonthWIB(t) },
      localization: { timeFormatter: (t: number) => dateTimeWIB(t), priceFormatter: (p: number) => p.toFixed(1) },
      handleScroll: false,
      handleScale: false,
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: color,
      topColor: `${color}55`,
      bottomColor: `${color}05`,
      lineWidth: 2,
      priceLineVisible: false,
    });
    series.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.equity })));
    series.createPriceLine({ price: 100, color: C.line, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: "" });
    chart.timeScale().fitContent();
    if (splitTime) {
      // garis pemisah in-sample | out-of-sample
      const marker = document.createElement("div");
      const place = () => {
        const x = chart.timeScale().timeToCoordinate(splitTime as UTCTimestamp);
        marker.style.cssText = `position:absolute;top:0;bottom:24px;left:${x ?? -10}px;border-left:1px dashed #f5a524;pointer-events:none`;
      };
      el.style.position = "relative";
      el.appendChild(marker);
      place();
      chart.timeScale().subscribeSizeChange(place);
    }
    return () => chart.remove();
  }, [points, splitTime, resolved]);

  if (points.length < 2) return <p className="text-sm text-muted">Belum cukup trade untuk kurva modal.</p>;
  return <div ref={container} className="h-48 w-full" />;
}
