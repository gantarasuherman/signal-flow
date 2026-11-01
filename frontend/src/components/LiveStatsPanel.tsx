"use client";

import { useEffect, useState } from "react";
import { MetricsGrid, MetricsTable } from "@/components/MetricsView";
import { endpoints } from "@/lib/api";
import type { LiveStats, Metrics, Source } from "@/lib/types";

const signed = (v: number, digits = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}`;

/** Rekap siklus BUY/SELL → CLOSE: berapa yang benar (untung) dan salah (rugi), lalu bersihnya. */
function CycleRecap({ m, risk, label }: { m: Metrics; risk: number; label: string }) {
  const winPct = (m.win_r ?? 0) * risk;
  const lossPct = (m.loss_r ?? 0) * risk;
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold text-muted">Rekap siklus · {label}</div>
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-buy/10 p-3">
          <div className="text-xs text-buy">✓ Benar (untung)</div>
          <div className="tabular text-2xl font-black text-buy">{m.wins}×</div>
          <div className="tabular text-sm text-buy">
            {signed(m.win_pips ?? 0)} pip · {signed(winPct, 2)}%
          </div>
        </div>
        <div className="rounded-xl bg-sell/10 p-3">
          <div className="text-xs text-sell">✗ Salah (rugi)</div>
          <div className="tabular text-2xl font-black text-sell">{m.losses}×</div>
          <div className="tabular text-sm text-sell">
            {signed(m.loss_pips ?? 0)} pip · {signed(lossPct, 2)}%
          </div>
        </div>
      </div>
      <div className="flex items-baseline justify-between rounded-xl bg-bg/60 px-3 py-2">
        <span className="text-sm text-fg-soft">Bersih {m.trades} siklus</span>
        <span className={`tabular font-black ${m.net_pips >= 0 ? "text-buy" : "text-sell"}`}>
          {signed(m.net_pips)} pip · {signed(m.return_pct, 2)}% modal
        </span>
      </div>
    </div>
  );
}

/** Kinerja sinyal LIVE yang sudah selesai (bila masuk tepat di harga entry). Periode dipilih
 *  di ringkasan ketepatan di atasnya. */
export function LiveStatsPanel({
  refreshKey,
  source,
  days,
  symbol,
}: {
  refreshKey: number;
  source: Source;
  days: number;
  /** kosong = semua instrumen */
  symbol: string;
}) {
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
      <h2 className="text-lg font-bold">Statistik {source === "ai" ? "AI Groq" : "strategi"}</h2>
      {error && <p className="text-sm text-sell">{error}</p>}
      {stats && stats.overall.trades === 0 && (
        <p className="text-sm text-muted">
          Belum ada sinyal yang selesai dalam {days} hari terakhir. Lihat halaman Backtest untuk kinerja historis.
        </p>
      )}
      {stats && stats.overall.trades > 0 && (
        <>
          {symbol && !stats.instruments[symbol]?.trades ? (
            <p className="text-sm text-muted">Belum ada siklus {symbol} yang selesai dalam periode ini.</p>
          ) : (
            <CycleRecap
              m={symbol ? stats.instruments[symbol] : stats.overall}
              risk={stats.risk_percent}
              label={symbol || "semua instrumen"}
            />
          )}
          <MetricsGrid m={stats.overall} />
          <MetricsTable
            rows={Object.entries(stats.instruments)
              .filter(([, m]) => m.trades > 0)
              .map(([symbol, m]) => ({ label: symbol, m }))}
          />
          <p className="text-[11px] text-muted">
            Satu siklus = BUY/SELL sampai ditutup (TP, SL, trailing stop, atau sinyal CLOSE). % modal
            dengan risiko {stats.risk_percent}% per sinyal. R = kelipatan risiko per sinyal. Drawdown % dihitung dengan risiko {stats.risk_percent}% per sinyal.
          </p>
        </>
      )}
    </section>
  );
}
