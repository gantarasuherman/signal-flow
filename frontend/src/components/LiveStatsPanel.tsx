"use client";

import { useEffect, useState } from "react";
import { MetricsGrid, MetricsTable } from "@/components/MetricsView";
import { endpoints } from "@/lib/api";
import type { LiveStats, Source } from "@/lib/types";

const RANGES = [7, 30, 90, 365];

/** Kinerja sinyal LIVE yang sudah selesai (bila masuk tepat di harga entry). */
export function LiveStatsPanel({ refreshKey, source }: { refreshKey: number; source: Source }) {
  const [days, setDays] = useState(30);
  const [stats, setStats] = useState<LiveStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    endpoints
      .stats(days, source)
      .then((s) => {
        setStats(s);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [days, refreshKey, source]);

  return (
    <section className="space-y-3 surface rounded-2xl p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-bold">Statistik {source === "ai" ? "AI Groq" : "strategi"}</h2>
        <div className="flex gap-1">
          {RANGES.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded-md px-2 py-1 text-xs ${d === days ? "bg-fg text-bg" : "bg-bg text-muted"}`}
            >
              {d}h
            </button>
          ))}
        </div>
      </div>
      {error && <p className="text-sm text-sell">{error}</p>}
      {stats && stats.overall.trades === 0 && (
        <p className="text-sm text-muted">
          Belum ada sinyal yang selesai dalam {days} hari terakhir. Lihat halaman Backtest untuk kinerja historis.
        </p>
      )}
      {stats && stats.overall.trades > 0 && (
        <>
          <MetricsGrid m={stats.overall} />
          <MetricsTable
            rows={Object.entries(stats.instruments)
              .filter(([, m]) => m.trades > 0)
              .map(([symbol, m]) => ({ label: symbol, m }))}
          />
          <p className="text-[11px] text-muted">
            R = kelipatan risiko per sinyal. Drawdown % dihitung dengan risiko {stats.risk_percent}% per sinyal.
          </p>
        </>
      )}
    </section>
  );
}
