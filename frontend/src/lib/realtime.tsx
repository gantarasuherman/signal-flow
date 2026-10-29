"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { WsMessage } from "./types";

type Status = "connecting" | "open" | "closed";
type Listener = (message: WsMessage) => void;
type Outgoing =
  | { action: "subscribe_live"; symbol: string; timeframe: string }
  | { action: "unsubscribe_live" }
  | { action: "ping" };

interface RealtimeContextValue {
  status: Status;
  /** selisih jam server − jam perangkat (ms), untuk countdown yang akurat */
  clockOffset: number;
  setClockFromServer: (serverIso: string) => void;
  subscribe: (listener: Listener) => () => void;
  send: (message: Outgoing) => void;
  /** bertambah setiap kali koneksi tersambung ulang → pemicu muat ulang data */
  connectionId: number;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

function wsUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws`;
}

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("connecting");
  const [clockOffset, setClockOffset] = useState(0);
  const [connectionId, setConnectionId] = useState(0);
  const listeners = useRef(new Set<Listener>());
  const socket = useRef<WebSocket | null>(null);
  const liveSubscription = useRef<Outgoing | null>(null);

  const setClockFromServer = useCallback((serverIso: string) => {
    setClockOffset(new Date(serverIso).getTime() - Date.now());
  }, []);

  useEffect(() => {
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      const current = socket.current;
      if (current && (current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING))
        return;
      setStatus("connecting");
      const ws = new WebSocket(wsUrl());
      socket.current = ws;

      ws.onopen = () => {
        retry = 0;
        setStatus("open");
        setConnectionId((id) => id + 1);
        if (liveSubscription.current) ws.send(JSON.stringify(liveSubscription.current));
      };
      ws.onmessage = (event) => {
        let message: WsMessage;
        try {
          message = JSON.parse(event.data as string) as WsMessage;
        } catch {
          return;
        }
        if (message.type === "hello") setClockFromServer(message.server_time);
        listeners.current.forEach((listener) => listener(message));
      };
      ws.onclose = () => {
        if (socket.current === ws) socket.current = null;
        setStatus("closed");
        if (disposed) return;
        const delay = Math.min(1000 * 2 ** retry, 15000);
        retry += 1;
        timer = setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
    };

    // iOS menutup WebSocket saat aplikasi di background; sambung lagi saat dibuka
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        clearTimeout(timer);
        retry = 0;
        connect();
      }
    };
    const keepAlive = setInterval(() => {
      if (socket.current?.readyState === WebSocket.OPEN)
        socket.current.send(JSON.stringify({ action: "ping" }));
    }, 25000);

    connect();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onVisible);
    return () => {
      disposed = true;
      clearTimeout(timer);
      clearInterval(keepAlive);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onVisible);
      socket.current?.close();
    };
  }, [setClockFromServer]);

  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  const send = useCallback((message: Outgoing) => {
    if (message.action === "subscribe_live") liveSubscription.current = message;
    if (message.action === "unsubscribe_live") liveSubscription.current = null;
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify(message));
  }, []);

  return (
    <RealtimeContext.Provider
      value={{ status, clockOffset, setClockFromServer, subscribe, send, connectionId }}
    >
      {children}
    </RealtimeContext.Provider>
  );
}

export function useRealtime(): RealtimeContextValue {
  const ctx = useContext(RealtimeContext);
  if (!ctx) throw new Error("useRealtime harus dipakai di dalam RealtimeProvider");
  return ctx;
}

/** Panggil `handler` untuk setiap pesan WebSocket; handler terbaru selalu dipakai. */
export function useRealtimeMessages(handler: (message: WsMessage) => void): void {
  const { subscribe } = useRealtime();
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => subscribe((message) => ref.current(message)), [subscribe]);
}
