"use client";

import { useCallback, useEffect, useState } from "react";
import { endpoints } from "./api";
import { useRealtime, useRealtimeMessages } from "./realtime";
import {
  TF_SECONDS,
  type ChartRead,
  type DashboardResponse,
  type InstrumentCard,
  type PatternsResponse,
  type Timeframe,
} from "./types";

/** Muat ulang saat aplikasi kembali dibuka (iOS menjeda halaman di background). */
function useOnVisible(callback: () => void) {
  useEffect(() => {
    const handler = () => document.visibilityState === "visible" && callback();
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [callback]);
}

const replaceCard = (cards: InstrumentCard[], card: InstrumentCard) =>
  cards.map((c) => (c.instrument.symbol === card.instrument.symbol ? card : c));

export function useDashboard() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { setClockFromServer, connectionId } = useRealtime();

  const load = useCallback(async () => {
    try {
      const res = await endpoints.dashboard();
      setData(res);
      setClockFromServer(res.server_time);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [setClockFromServer]);

  // Muat saat pertama & setiap kali WebSocket tersambung ulang (bisa ada event yang terlewat)
  useEffect(() => {
    void load();
  }, [load, connectionId]);
  useOnVisible(load);

  useRealtimeMessages((msg) => {
    if (msg.type !== "card") return;
    setData((prev) => {
      if (!prev) return prev;
      return msg.data.source === "ai"
        ? { ...prev, ai_cards: replaceCard(prev.ai_cards, msg.data) }
        : { ...prev, cards: replaceCard(prev.cards, msg.data) };
    });
  });

  return { data, error, reload: load };
}

/** Kartu strategi (teruji) dan kartu AI Groq untuk satu instrumen. */
export function useInstrumentCard(symbol: string) {
  const [card, setCard] = useState<InstrumentCard | null>(null);
  const [aiCard, setAiCard] = useState<InstrumentCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const { connectionId } = useRealtime();

  const load = useCallback(async () => {
    try {
      const [rule, ai] = await Promise.all([endpoints.card(symbol), endpoints.card(symbol, "ai")]);
      setCard(rule);
      setAiCard(ai);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [symbol]);

  useEffect(() => {
    void load();
  }, [load, connectionId]);
  useOnVisible(load);

  useRealtimeMessages((msg) => {
    if (msg.type !== "card" || msg.data.instrument.symbol !== symbol) return;
    if (msg.data.source === "ai") setAiCard(msg.data);
    else setCard(msg.data);
    setReloadKey((k) => k + 1); // candle baru tutup / sinyal baru → muat ulang grafik
  });

  return { card, aiCard, setAiCard, error, reloadKey };
}

/** Jeda setelah candle tutup agar data candle tersebut sudah tersedia di penyedia data. */
const CANDLE_SETTLE_MS = 8000;
/** Batas bawah jeda muat ulang (M1 tetap 5 menit) agar kuota data gratis tidak cepat habis. */
const MIN_RELOAD_SECONDS = 300;

/**
 * Angka yang naik setiap kali candle di timeframe `tf` tutup (plus jeda singkat; M1 dibatasi
 * tiap 5 menit), dan saat aplikasi dibuka kembali. Dipakai untuk memuat ulang grafik, analisis chart, dan pola
 * mengikuti timeframe yang sedang dilihat, bukan hanya setiap 15 menit.
 */
export function useCandleTick(tf: Timeframe | null): number {
  const [tick, setTick] = useState(0);
  const bump = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!tf) return;
    const period = Math.max(TF_SECONDS[tf], MIN_RELOAD_SECONDS) * 1000;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      const now = Date.now();
      const next = Math.floor(now / period) * period + period + CANDLE_SETTLE_MS;
      timer = setTimeout(() => {
        bump();
        schedule();
      }, next - now);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [tf, bump]);
  useOnVisible(bump);

  return tick;
}

/** Pola candlestick + peluang historisnya untuk timeframe grafik (dipakai panel & grafik). */
export function usePatterns(symbol: string, tf: Timeframe | null, reloadKey: number) {
  const [data, setData] = useState<PatternsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tf) return; // tunggu grafik menentukan timeframe-nya
    let active = true;
    endpoints
      .patterns(symbol, tf)
      .then((res) => {
        if (!active) return;
        setData(res);
        setError(null);
      })
      .catch((e: Error) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [symbol, tf, reloadKey]);

  return { data, error };
}

/** Analisis kondisi chart untuk timeframe grafik (dipakai kartu STRATEGI & grafik). */
export function useChartRead(symbol: string, tf: Timeframe | null, reloadKey: number) {
  const [data, setData] = useState<ChartRead | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tf) return;
    let active = true;
    endpoints
      .chartAnalysis(symbol, tf)
      .then((r) => {
        if (!active) return;
        setData(r);
        setError(null);
      })
      .catch((e: Error) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [symbol, tf, reloadKey]);

  return { data, error };
}
