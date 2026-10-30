"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { endpoints } from "@/lib/api";
import { useCandleTick, useChartRead, useInstrumentCard, usePatterns } from "@/lib/hooks";
import { analysisWindow, bestPattern } from "@/lib/patternHint";
import type { PredictionSummary, SignalView, Timeframe } from "@/lib/types";
import { Disclaimer } from "./Disclaimer";
import { SignalCard } from "./SignalCard";
import { AiPanel } from "./AiPanel";
import { ChartAnalysis } from "./ChartAnalysis";
import { NextCandleStrip } from "./NextCandleStrip";
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
  // Muat ulang tampilan grafik setiap candle timeframe grafik tutup, selain saat ada analisis M15 baru
  const candleTick = useCandleTick(chartTf);
  const viewKey = reloadKey + candleTick;
  const patterns = usePatterns(symbol, chartTf, viewKey);
  const chartRead = useChartRead(symbol, chartTf, viewKey);
  // Uji maju prediksi pola untuk instrumen & timeframe grafik ini
  const [forward, setForward] = useState<PredictionSummary | null>(null);
  useEffect(() => {
    if (!chartTf) return;
    let active = true;
    endpoints
      .predictions(symbol, chartTf)
      .then((r) => active && setForward(r))
      .catch(() => active && setForward(null));
    return () => {
      active = false;
    };
  }, [symbol, chartTf, viewKey]);
  // Periode analisis = candle timeframe grafik yang sedang berjalan; dihitung ulang tiap candle tutup
  const window = useMemo(() => (chartTf ? analysisWindow(chartTf) : null), [chartTf, viewKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const patternHint = useMemo(() => bestPattern(patterns.data, chartTf), [patterns.data, chartTf]);

  useEffect(() => setLivePrice(null), [symbol]);
  useEffect(() => {
    endpoints
      .signals({ symbol, limit: 100 })
      .then(setHistory)
      .catch(() => setHistory([]));
    // Muat ulang titik BUY/SELL/CLOSE setiap grafik refresh dan setiap sinyal (strategi/AI) berubah
  }, [symbol, viewKey, card?.signal?.id, card?.signal?.status, aiCard?.signal?.id, aiCard?.signal?.status]);

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
        <ChartAnalysis data={chartRead.data} error={chartRead.error} window={window} />
      </SignalStrip>
      <ValidationNotice symbol={symbol} />
      <AiPanel symbol={symbol} card={aiCard} livePrice={livePrice} onResult={setAiCard} />
      <NextCandleStrip symbol={symbol} timeframe={chartTf} reloadKey={viewKey} />
      <PriceChart
        symbol={symbol}
        digits={card.instrument.digits}
        pipSize={card.instrument.pip_size}
        spreadPips={card.instrument.spread_pips}
        signals={activeSignals}
        history={history}
        reloadKey={viewKey}
        onLivePrice={setLivePrice}
        onTimeframe={setChartTf}
        patternHint={patternHint}
        chartRead={chartRead.data}
        analysisWindow={window}
        forward={forward}
      />
      <PatternPanel symbol={symbol} data={patterns.data} error={patterns.error} />
      <SignalCard card={card} livePrice={livePrice} />
      {aiCard?.signal && (aiCard.signal.status === "ACTIVE" || aiCard.signal.status === "EXPIRED" || aiCard.is_new_event) && (
        <SignalCard card={aiCard} livePrice={livePrice} />
      )}
      <Disclaimer />
    </div>
  );
}
