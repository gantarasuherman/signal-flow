"use client";

import { useCallback, useEffect, useState } from "react";
import { endpoints } from "./api";
import { useRealtime, useRealtimeMessages } from "./realtime";
import type { DashboardResponse, InstrumentCard } from "./types";

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
