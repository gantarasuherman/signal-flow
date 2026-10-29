"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { endpoints } from "@/lib/api";
import type { StrategyStatus } from "@/lib/types";

let cache: { at: number; data: StrategyStatus[] } | null = null;
const CACHE_MS = 5 * 60 * 1000;

/** Status validasi backtest strategi aktif untuk satu instrumen. */
export function useStrategyStatus(symbol: string): StrategyStatus | null {
  const [status, setStatus] = useState<StrategyStatus | null>(null);
  useEffect(() => {
    let active = true;
    const pick = (data: StrategyStatus[]) => active && setStatus(data.find((s) => s.symbol === symbol) ?? null);
    if (cache && Date.now() - cache.at < CACHE_MS) pick(cache.data);
    else
      endpoints
        .strategyStatus()
        .then((data) => {
          cache = { at: Date.now(), data };
          pick(data);
        })
        .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [symbol]);
  return status;
}

/**
 * Peringatan bila strategi aktif belum lolos uji backtest out-of-sample.
 * Hilang otomatis setelah backtest terbaru untuk strategi yang sama lolos.
 */
export function ValidationNotice({ symbol }: { symbol: string }) {
  const status = useStrategyStatus(symbol);
  if (!status) return null;
  if (status.strategy === "disabled") {
    return (
      <Link href="/backtest" className="block rounded-lg bg-panel px-3 py-1.5 text-[11px] text-muted">
        ⏸ Sinyal {symbol} dinonaktifkan — belum ada strategi yang lolos uji backtest. Grafik tetap bisa dipantau.
      </Link>
    );
  }
  if (status.validated) {
    const o = status.out_of_sample;
    return (
      <Link href="/backtest" className="block rounded-lg bg-buy/10 px-3 py-1.5 text-[11px] text-ok">
        ✓ Strategi {status.strategy} lolos uji backtest
        {o && ` (out-of-sample PF ${o.profit_factor}, ${o.trades} trade)`}. Tetap bukan jaminan profit.
      </Link>
    );
  }
  return (
    <Link href="/backtest" className="block rounded-lg bg-close/10 px-3 py-1.5 text-[11px] text-warn">
      ⚠ Strategi {status.strategy} untuk {symbol} <strong>belum terbukti menguntungkan</strong> di backtest — {status.reason}{" "}
      Gunakan akun demo.
    </Link>
  );
}
