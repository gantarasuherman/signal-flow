"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { endpoints } from "@/lib/api";
import { useInstrumentCard } from "@/lib/hooks";
import type { SignalView, Timeframe } from "@/lib/types";
import { Disclaimer } from "./Disclaimer";
import { SignalCard } from "./SignalCard";
import { AiPanel } from "./AiPanel";
import { ChartAnalysis } from "./ChartAnalysis";
import { PatternPanel } from "./PatternPanel";
import { SignalStrip } from "./SignalStrip";
import { ValidationNotice } from "./ValidationNotice";

// Lightweight Charts hanya berjalan di browser
const PriceChart = dynamic(() => import("@/components/PriceChart"), {
  ssr: false,
  loading: () => <div className="h-[55vh] min-h-[340px] animate-pulse rounded-xl bg-panel" />,
});

/** Layar pantau satu instrumen: instruksi sinyal (strategi & AI) + grafik + detail. */
export function ChartMonitor({ symbol }: { symbol: string }) {
  const { card, aiCard, setAiCard, error, reloadKey } = useInstrumentCard(symbol);
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [history, setHistory] = useState<SignalView[]>([]);
  const [chartTf, setChartTf] = useState<Timeframe | null>(null);

  useEffect(() => setLivePrice(null), [symbol]);
  useEffect(() => {
    endpoints
      .signals({ symbol, limit: 100 })
      .then(setHistory)
      .catch(() => setHistory([]));
  }, [symbol, reloadKey]);

  // Garis Entry/SL/TP untuk sinyal yang masih aktif dari kedua sumber
  const activeSignals = useMemo(
    () =>
      [card?.signal, aiCard?.signal].filter(
        (s): s is SignalView => !!s && s.action !== "CLOSE" && (s.status === "ACTIVE" || s.status === "EXPIRED"),
      ),
    [card?.signal, aiCard?.signal],
  );

  if (error) return <p className="rounded-xl bg-sell/10 px-4 py-3 text-sm text-err">{error}</p>;
  if (!card)
    return (
      <div className="space-y-3">
        <div className="h-16 animate-pulse rounded-2xl bg-panel" />
        <div className="h-[55vh] min-h-[340px] animate-pulse rounded-xl bg-panel" />
      </div>
    );

  return (
    <div className="space-y-3">
      <SignalStrip card={card} livePrice={livePrice} hero>
        <ChartAnalysis symbol={symbol} timeframe={chartTf} reloadKey={reloadKey} />
      </SignalStrip>
      <ValidationNotice symbol={symbol} />
      <AiPanel symbol={symbol} card={aiCard} livePrice={livePrice} onResult={setAiCard} />
      <PriceChart
        symbol={symbol}
        digits={card.instrument.digits}
        signals={activeSignals}
        history={history}
        reloadKey={reloadKey}
        onLivePrice={setLivePrice}
        onTimeframe={setChartTf}
      />
      <PatternPanel symbol={symbol} reloadKey={reloadKey} activeTf={chartTf} />
      <SignalCard card={card} livePrice={livePrice} />
      {aiCard?.signal && (aiCard.signal.status === "ACTIVE" || aiCard.signal.status === "EXPIRED" || aiCard.is_new_event) && (
        <SignalCard card={aiCard} livePrice={livePrice} />
      )}
      <Disclaimer />
    </div>
  );
}
