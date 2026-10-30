"use client";

import type { AnalysisWindow } from "@/lib/patternHint";
import type { ChartRead } from "@/lib/types";

const LEAN_STYLE: Record<ChartRead["lean"], { chip: string; icon: string }> = {
  naik: { chip: "bg-buy/20 text-buy", icon: "▲" },
  turun: { chip: "bg-sell/20 text-sell", icon: "▼" },
  netral: { chip: "bg-wait/20 text-fg-soft", icon: "■" },
};

const DOT: Record<ChartRead["points"][number]["tone"], string> = {
  up: "bg-buy",
  down: "bg-sell",
  neutral: "bg-muted",
  warn: "bg-close",
};

/**
 * Analisis kondisi chart (tren H4/H1/grafik, momentum, RSI, level) di dalam kartu STRATEGI.
 * Ringkasan apa yang terlihat di grafik — bukan sinyal strategi yang lolos backtest.
 * Data dimuat di ChartMonitor (`useChartRead`) agar grafik menampilkan hasil yang sama.
 */
export function ChartAnalysis({
  data,
  error,
  window,
}: {
  data: ChartRead | null;
  error: string | null;
  window?: AnalysisWindow | null;
}) {

  if (error) return <p className="text-xs text-err">Analisis chart gagal dimuat: {error}</p>;
  if (!data) return <div className="h-12 animate-pulse rounded-lg bg-white/5" />;

  const st = LEAN_STYLE[data.lean];
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-bold tracking-widest text-muted">ANALISIS CHART · {data.timeframe}</span>
        <span className={`rounded-md px-1.5 py-0.5 text-[11px] font-bold ${st.chip}`}>
          {st.icon} {data.lean.toUpperCase()}
          {data.lean !== "netral" && ` · ${data.strength}`}
        </span>
      </div>
      <div className="font-semibold leading-snug">{data.headline}</div>
      {window && window.timeframe === data.timeframe && (
        <p className="tabular text-xs font-semibold text-fg-soft">
          ⏱ Periode analisis: {window.label}{" "}
          <span className="font-normal text-muted">(1 candle {data.timeframe})</span>
        </p>
      )}
      <p className="text-xs leading-snug text-fg-soft">{data.watch}</p>
      <details className="group">
        <summary className="cursor-pointer list-none text-xs font-semibold text-accent">
          <span className="group-open:hidden">Lihat rincian ({data.points.length}) ›</span>
          <span className="hidden group-open:inline">Sembunyikan rincian</span>
        </summary>
        <ul className="mt-2 space-y-1.5">
          {data.points.map((p) => (
            <li key={p.text} className="flex gap-2 text-xs leading-snug text-fg-soft">
              <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${DOT[p.tone]}`} />
              <span>{p.text}</span>
            </li>
          ))}
        </ul>
      </details>
      <p className="text-[10px] leading-snug text-muted">
        Ringkasan kondisi chart, bukan sinyal strategi yang lolos uji. Instruksi di atas tetap yang utama.
      </p>
    </div>
  );
}
