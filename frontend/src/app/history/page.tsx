"use client";

import { useCallback, useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { LiveStatsPanel } from "@/components/LiveStatsPanel";
import { endpoints } from "@/lib/api";
import { dateTimeWIB, formatPips, formatPrice } from "@/lib/format";
import { useRealtimeMessages } from "@/lib/realtime";
import { ACTION_STYLE, STATUS_STYLE } from "@/lib/signal";
import type { SignalView, Source } from "@/lib/types";

const SYMBOLS = ["", "XAUUSD", "EURUSD", "GBPUSD", "USDJPY"];
const PAGE = 30;

function Row({ s }: { s: SignalView }) {
  const [open, setOpen] = useState(false);
  const style = ACTION_STYLE[s.action];
  const result = s.result_pips;
  return (
    <li className="surface rounded-xl p-3" onClick={() => setOpen(!open)}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`w-14 text-lg font-black ${style.text}`}>{s.action}</span>
          <div>
            <div className="font-semibold">
              {s.symbol}
              {s.source === "ai" && (
                <span className="ml-1.5 rounded bg-ai/20 px-1 py-0.5 text-[10px] font-bold text-ai">AI</span>
              )}
            </div>
            <div className="text-xs text-muted">{dateTimeWIB(s.signal_time)} WIB</div>
          </div>
        </div>
        <div className="text-right">
          {s.action !== "CLOSE" && (
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[s.status]}`}>{s.status_label}</span>
          )}
          {s.action === "CLOSE" && s.closes_action && <span className="text-xs text-muted">tutup {s.closes_action}</span>}
          {result != null && (
            <div className={`tabular text-sm font-bold ${result >= 0 ? "text-buy" : "text-sell"}`}>
              {formatPips(result, true)} pip
            </div>
          )}
        </div>
      </div>
      {s.action !== "CLOSE" && (
        <div className="tabular mt-2 grid grid-cols-3 gap-2 text-xs">
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
      )}
      {(open || s.action === "CLOSE") && (
        <p className="mt-2 text-sm text-fg-soft">{s.action === "CLOSE" ? s.close_reason : s.reason_text}</p>
      )}
    </li>
  );
}

export default function HistoryPage() {
  const [symbol, setSymbol] = useState("");
  const [source, setSource] = useState<Source>("rule");
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("source") === "ai") setSource("ai");
  }, []);
  const [items, setItems] = useState<SignalView[]>([]);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (beforeId?: number) => {
      setLoading(true);
      try {
        const page = await endpoints.signals({ symbol: symbol || undefined, source, limit: PAGE, beforeId });
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
        <div className="grid grid-cols-2 gap-1 rounded-xl bg-panel p-1">
          {(["rule", "ai"] as const).map((src) => (
            <button
              key={src}
              onClick={() => setSource(src)}
              className={`rounded-lg py-2 text-sm font-semibold ${source === src ? "bg-fg text-bg" : "text-muted"}`}
            >
              {src === "rule" ? "Strategi (teruji)" : "AI Groq (eksperimen)"}
            </button>
          ))}
        </div>
        <LiveStatsPanel refreshKey={statsKey} source={source} />
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
          <p className="py-10 text-center text-sm text-muted">Belum ada sinyal.</p>
        )}
        <ul className="space-y-2">
          {items.map((s) => (
            <Row key={s.id} s={s} />
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
          Hasil dihitung bila masuk tepat di harga entry, sudah dikurangi spread.
        </p>
      </main>
    </>
  );
}
