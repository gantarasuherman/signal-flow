"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { ChartMonitor } from "@/components/ChartMonitor";
import { useDashboard } from "@/lib/hooks";
import { ACTION_STYLE } from "@/lib/signal";

const STORAGE_KEY = "signalflow:symbol";
const FALLBACK = "XAUUSD";

function Monitor() {
  const router = useRouter();
  const params = useSearchParams();
  const { data, error } = useDashboard();
  const [symbol, setSymbol] = useState<string | null>(null);

  // Instrumen terpilih: ?s= di URL → pilihan terakhir → XAUUSD
  useEffect(() => {
    const fromUrl = params.get("s")?.toUpperCase();
    let remembered: string | null = null;
    try {
      remembered = localStorage.getItem(STORAGE_KEY);
    } catch {
      // abaikan
    }
    setSymbol(fromUrl || remembered || FALLBACK);
  }, [params]);

  const select = (s: string) => {
    setSymbol(s);
    try {
      localStorage.setItem(STORAGE_KEY, s);
    } catch {
      // abaikan
    }
    router.replace(`/?s=${s}`, { scroll: false });
  };

  const cards = data?.cards ?? [];
  const aiBySymbol = new Map((data?.ai_cards ?? []).map((c) => [c.instrument.symbol, c]));
  const current = cards.find((c) => c.instrument.symbol === symbol);

  return (
    <>
      <AppHeader title={symbol ?? "SignalFlow"} subtitle={current?.instrument.name ?? "Sinyal M15"} showWakeLock />
      <main className="mx-auto max-w-3xl space-y-3 px-4 py-3">
        {/* Tab instrumen dengan lencana aksi: sinyal di pair lain tetap terlihat */}
        <div className="grid grid-cols-4 gap-1.5">

          {cards.map((c) => {
            const style = ACTION_STYLE[c.action];
            const active = c.instrument.symbol === symbol;
            const idle = !active && Boolean(c.analysis?.details?.idle);
            return (
              <button
                key={c.instrument.symbol}
                onClick={() => select(c.instrument.symbol)}
                aria-pressed={active}
                className={`relative min-w-0 overflow-hidden rounded-2xl border-2 py-2 pl-2.5 pr-1.5 text-left transition ${
                  active
                    ? "border-brand bg-brand/15 shadow-[0_0_14px_-2px_var(--brand)]"
                    : "border-line bg-panel/60 opacity-70 hover:opacity-100"
                }`}
              >
                <div className={`text-sm font-bold ${active ? "text-brand" : ""}`}>{c.instrument.symbol}</div>
                <span className={`absolute inset-y-0 left-0 w-1 ${style.bar}`} />
                {idle ? (
                  <div className="truncate text-[10px] font-semibold text-muted">nonaktif</div>
                ) : (
                  <div className={`text-xs font-black ${style.text}`}>
                    {style.icon} {style.label}
                  </div>
                )}
                {!idle && aiBySymbol.get(c.instrument.symbol) && (
                  <div className="text-[10px] font-bold text-ai">
                    AI {ACTION_STYLE[aiBySymbol.get(c.instrument.symbol)!.action].label}
                  </div>
                )}
                {(c.is_new_event || aiBySymbol.get(c.instrument.symbol)?.is_new_event) && (
                  <span className={`absolute right-1.5 top-1.5 h-2 w-2 animate-pulse rounded-full ${style.text} bg-current`} />
                )}
              </button>
            );
          })}
        </div>
        {error && !data && <p className="text-sm text-sell">Gagal memuat data: {error}</p>}
        {symbol && <ChartMonitor key={symbol} symbol={symbol} />}
      </main>
    </>
  );
}

export default function Home() {
  return (
    <Suspense fallback={null}>
      <Monitor />
    </Suspense>
  );
}
