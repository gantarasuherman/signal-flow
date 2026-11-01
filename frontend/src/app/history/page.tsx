"use client";

import { useCallback, useEffect, useState } from "react";
import { PredictionLog } from "@/components/PredictionLog";
import { AccuracySummary } from "@/components/AccuracySummary";
import { AppHeader } from "@/components/AppHeader";
import { LiveStatsPanel } from "@/components/LiveStatsPanel";
import { endpoints } from "@/lib/api";
import { dateTimeWIB, formatPips, formatPrice, formatUSD } from "@/lib/format";
import { useRealtimeMessages } from "@/lib/realtime";
import { TF_MINUTES } from "@/lib/patternHint";
import { ACTION_STYLE, STATUS_STYLE } from "@/lib/signal";
import type { SignalView, Source } from "@/lib/types";

const SYMBOLS = ["", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY"];
const PAGE = 30;

/** Lama siklus. `closed_at` = waktu buka candle tempat posisi ditutup, jadi batas atasnya
 *  adalah akhir candle itu. */
function durationText(s: SignalView): string {
  const end = new Date(s.closed_at!).getTime() + TF_MINUTES[s.timeframe] * 60000;
  const minutes = Math.round((end - new Date(s.signal_time).getTime()) / 60000);
  if (minutes < 60) return `${minutes} menit`;
  if (minutes < 48 * 60) return `${Math.floor(minutes / 60)} jam ${minutes % 60 ? `${minutes % 60} menit` : ""}`.trim();
  return `${Math.round(minutes / 1440)} hari`;
}

/** Satu siklus BUY/SELL dari masuk sampai CLOSE: benar (untung) atau salah (rugi). */
function CycleRow({ s }: { s: SignalView }) {
  const [open, setOpen] = useState(false);
  const style = ACTION_STYLE[s.action];
  const result = s.result_pips;
  const finished = result != null && s.status !== "ACTIVE";
  const win = finished && result > 0;
  // Gerak harga dari entry ke harga CLOSE, tanpa memperhitungkan arah sinyal
  const move = s.entry != null && s.close_price != null ? (s.close_price - s.entry) / s.pip_size : null;
  const risk = (s.sl_pips ?? 0) + (s.spread_pips ?? 0);
  const r = finished && risk > 0 ? result / risk : null;
  const pct = r != null ? r * s.risk_percent : null;
  const money = r != null && s.risk_amount != null ? r * s.risk_amount : null;

  const verdict = finished
    ? win
      ? { text: "✓ BENAR · untung", cls: "bg-buy/15 text-buy", border: "border-l-buy" }
      : { text: "✗ SALAH · rugi", cls: "bg-sell/15 text-sell", border: "border-l-sell" }
    : s.status === "ACTIVE"
      ? { text: "Berjalan", cls: "bg-wait/20 text-fg-soft", border: "border-l-line" }
      : { text: s.status_label, cls: STATUS_STYLE[s.status], border: "border-l-line" };

  return (
    <li
      className={`surface cursor-pointer rounded-xl border-l-4 p-3 ${verdict.border}`}
      onClick={() => setOpen(!open)}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className={`text-lg font-black ${style.text}`}>
              {style.icon} {s.action}
            </span>
            <span className="font-semibold">{s.symbol}</span>
            <span className="text-[11px] text-muted">{s.timeframe}</span>
            {s.source === "ai" && (
              <span className="rounded bg-ai/20 px-1 py-0.5 text-[10px] font-bold text-ai">AI</span>
            )}
          </div>
          <div className="text-xs text-muted">{dateTimeWIB(s.signal_time)} WIB</div>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold ${verdict.cls}`}>
          {verdict.text}
        </span>
      </div>

      <div className="tabular mt-2 flex items-center gap-2 text-sm">
        <span>{formatPrice(s.entry, s.digits)}</span>
        <span className="text-muted">→</span>
        <span>{finished ? formatPrice(s.close_price, s.digits) : formatPrice(s.current_price, s.digits)}</span>
        {finished && s.closed_at && (
          <span className="text-xs text-muted">· ≤ {durationText(s)}</span>
        )}
      </div>

      {finished && (
        <>
          {move != null && (
            <p className="mt-1 text-xs text-fg-soft">
              Harga {move >= 0 ? "naik" : "turun"} {formatPips(move)} pip —{" "}
              {win ? `searah ${s.action}` : `berlawanan dengan ${s.action}`}.
            </p>
          )}
          <div className="tabular mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className={`text-lg font-black ${win ? "text-buy" : "text-sell"}`}>
              {win ? "Untung" : "Rugi"} {formatPips(result, true)} pip
            </span>
            {pct != null && (
              <span className={`text-sm font-semibold ${win ? "text-buy" : "text-sell"}`}>
                {pct > 0 ? "+" : ""}
                {pct.toFixed(2)}% modal
              </span>
            )}
            {money != null && (
              <span className={`text-sm ${win ? "text-buy" : "text-sell"}`}>
                ≈ {money > 0 ? "+" : ""}
                {formatUSD(money)}
              </span>
            )}
          </div>
        </>
      )}
      {s.status === "ACTIVE" && s.distance_from_entry_pips != null && (
        <p className="tabular mt-1 text-xs text-fg-soft">
          Sementara {formatPips(s.distance_from_entry_pips, true)} pip — belum ditutup.
        </p>
      )}

      {open && (
        <div className="mt-2 space-y-2 border-t border-line pt-2">
          <div className="tabular grid grid-cols-3 gap-2 text-xs">
            <div>
              <div className="text-muted">Entry</div>
              {formatPrice(s.entry, s.digits)}
            </div>
            <div>
              <div className="text-muted">SL ({formatPips(s.sl_pips)})</div>
              <span className="text-sell">{formatPrice(s.stop_loss, s.digits)}</span>
            </div>
            <div>
              <div className="text-muted">TP ({formatPips(s.tp_pips)})</div>
              <span className="text-buy">{formatPrice(s.take_profit, s.digits)}</span>
            </div>
          </div>
          <p className="text-sm text-fg-soft">
            <span className="text-muted">Alasan masuk: </span>
            {s.reason_text}
          </p>
          {s.close_reason && (
            <p className="text-sm text-fg-soft">
              <span className="text-muted">Ditutup karena: </span>
              {s.close_reason}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export default function HistoryPage() {
  const [symbol, setSymbol] = useState("");
  const [source, setSource] = useState<Source>("rule");
  // Tab ketiga: uji maju prediksi pola (bukan daftar sinyal)
  const [showPredictions, setShowPredictions] = useState(false);
  const [days, setDays] = useState(30);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("source") === "ai")
      setSource("ai");
  }, []);
  const [items, setItems] = useState<SignalView[]>([]);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (beforeId?: number) => {
      setLoading(true);
      try {
        const page = await endpoints.signals({
          symbol: symbol || undefined,
          source,
          actions: ["BUY", "SELL"],
          limit: PAGE,
          beforeId,
        });
        setItems((prev) => (beforeId ? [...prev, ...page] : page));
        setDone(page.length < PAGE);
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [symbol, source],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const [statsKey, setStatsKey] = useState(0);
  useRealtimeMessages((msg) => {
    if (msg.type === "signal") {
      void load();
      setStatsKey((k) => k + 1);
    }
  });

  return (
    <>
      <AppHeader title="Riwayat sinyal" />
      <main className="mx-auto max-w-3xl space-y-3 px-4 py-4">
        <AccuracySummary days={days} onDays={setDays} refreshKey={statsKey} />
        <div className="grid grid-cols-3 gap-1 rounded-xl bg-panel p-1">
          {(["rule", "ai"] as const).map((src) => (
            <button
              key={src}
              onClick={() => {
                setSource(src);
                setShowPredictions(false);
              }}
              className={`rounded-lg py-2 text-sm font-semibold ${
                !showPredictions && source === src
                  ? "bg-fg text-bg"
                  : "text-muted"
              }`}
            >
              {src === "rule" ? "Strategi" : "AI Groq"}
            </button>
          ))}
          <button
            onClick={() => setShowPredictions(true)}
            className={`rounded-lg py-2 text-sm font-semibold ${showPredictions ? "bg-fg text-bg" : "text-muted"}`}
          >
            Prediksi pola
          </button>
        </div>
        {showPredictions ? (
          <PredictionLog />
        ) : (
          <>
            <LiveStatsPanel refreshKey={statsKey} source={source} days={days} symbol={symbol} />
            <div className="flex gap-1 overflow-x-auto">
              {SYMBOLS.map((s) => (
                <button
                  key={s || "all"}
                  onClick={() => setSymbol(s)}
                  className={`rounded-full px-3 py-1.5 text-sm ${symbol === s ? "bg-fg text-bg" : "bg-panel text-muted"}`}
                >
                  {s || "Semua"}
                </button>
              ))}
            </div>
            {error && <p className="text-sm text-sell">{error}</p>}
            {!loading && items.length === 0 && !error && (
              <p className="py-10 text-center text-sm text-muted">
                Belum ada sinyal.
              </p>
            )}
            <ul className="space-y-2">
              {items.map((s) => (
                <CycleRow key={s.id} s={s} />
              ))}
            </ul>
            {!done && items.length > 0 && (
              <button
                disabled={loading}
                onClick={() => load(items.at(-1)?.id)}
                className="w-full rounded-xl bg-panel py-3 text-sm text-muted"
              >
                {loading ? "Memuat…" : "Muat lebih banyak"}
              </button>
            )}
            <p className="text-center text-xs text-muted">
              Hasil dihitung bila masuk tepat di harga entry, sudah dikurangi
              spread.
            </p>
          </>
        )}
      </main>
    </>
  );
}
