"use client";

import { useEffect, useState } from "react";
import { endpoints } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { InstrumentCard } from "@/lib/types";
import { SignalStrip } from "./SignalStrip";

interface Props {
  symbol: string;
  card: InstrumentCard | null;
  livePrice: number | null;
  onResult: (card: InstrumentCard) => void;
}

/**
 * Analisis AI sesuai permintaan: AI Groq hanya bekerja saat tombol ditekan, lalu memberi
 * status BUY / SELL / CLOSE / WAIT untuk instrumen yang sedang dibuka.
 */
export function AiPanel({ symbol, card, livePrice, onResult }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    setError(null);
    endpoints
      .aiWarning(symbol)
      .then((r) => setWarning(r.warning))
      .catch(() => setWarning(null));
  }, [symbol]);

  useEffect(() => {
    if (cooldownUntil <= Date.now()) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [cooldownUntil]);

  const cooldown = Math.max(0, Math.ceil((cooldownUntil - now) / 1000));
  const hasPosition = card?.signal?.status === "ACTIVE" || card?.signal?.status === "EXPIRED";
  const analyzedAt = card?.analysis && !card.analysis.details?.idle ? card.analysis.analyzed_at : null;

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await endpoints.runAi(symbol);
      onResult(res.card);
      setWarning(res.warning);
      setCooldownUntil(Date.now() + res.cooldown_seconds * 1000);
      setNow(Date.now());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="surface space-y-3 rounded-2xl p-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-bold">
            🧠 Analisis AI <span className="text-[10px] font-semibold text-ai">GROQ · eksperimen</span>
          </div>
          <div className="text-[11px] text-muted">
            {analyzedAt
              ? `Terakhir dianalisis ${relativeTime(analyzedAt)}`
              : `Tekan tombol untuk meminta keputusan AI tentang ${symbol} sekarang.`}
          </div>
        </div>
        <button
          onClick={run}
          disabled={loading || cooldown > 0}
          className="shrink-0 rounded-xl bg-ai px-4 py-2.5 text-sm font-bold text-bg shadow-sm transition active:scale-95 disabled:opacity-50"
        >
          {loading ? "Menganalisis…" : cooldown > 0 ? `Tunggu ${cooldown} dtk` : hasPosition ? "Cek posisi" : "Analisis AI"}
        </button>
      </div>

      {loading && (
        <div className="flex items-center gap-2 rounded-xl bg-ai/10 px-3 py-2 text-xs text-ai">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-ai border-t-transparent" />
          AI membaca grafik {symbol} (tren H4/H1/M15, indikator, pola candlestick)… ±10–30 detik
        </div>
      )}
      {error && <p className="rounded-xl bg-sell/10 px-3 py-2 text-xs text-err">{error}</p>}
      {warning && <p className="rounded-xl bg-close/10 px-3 py-2 text-xs text-warn">⚠ {warning}</p>}

      {card && analyzedAt && <SignalStrip card={card} livePrice={livePrice} />}

      <p className="text-[11px] leading-snug text-muted">
        {hasPosition
          ? "Ada posisi AI aktif: TP/SL dipantau otomatis. Tekan Cek posisi untuk menanyakan apakah perlu CLOSE."
          : "AI hanya bekerja saat tombol ditekan (hemat kuota). Hasil: BUY / SELL / WAIT; belum bisa di-backtest, gunakan akun demo."}
      </p>
    </section>
  );
}
