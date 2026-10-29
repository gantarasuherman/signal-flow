"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "signalflow:wakelock";

/**
 * Menjaga layar HP tetap menyala selama dashboard terbuka (Screen Wake Lock API).
 * Browser melepas kunci saat aplikasi ditutup/di background, jadi dikunci ulang saat
 * aplikasi kembali terlihat.
 */
export function WakeLockToggle() {
  const [supported, setSupported] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const lock = useRef<WakeLockSentinel | null>(null);

  const acquire = useCallback(async () => {
    if (lock.current || document.visibilityState !== "visible") return;
    try {
      lock.current = await navigator.wakeLock.request("screen");
      lock.current.addEventListener("release", () => {
        lock.current = null;
      });
    } catch {
      // ditolak (mis. mode hemat daya) — coba lagi saat aplikasi dibuka berikutnya
    }
  }, []);

  useEffect(() => {
    setSupported("wakeLock" in navigator);
    try {
      setEnabled(localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      // localStorage tidak tersedia
    }
  }, []);

  useEffect(() => {
    if (!supported) return;
    if (!enabled) {
      void lock.current?.release();
      lock.current = null;
      return;
    }
    void acquire();
    const onVisible = () => void acquire();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [enabled, supported, acquire]);

  if (!supported) return null;

  const toggle = () => {
    const next = !enabled;
    setEnabled(next);
    try {
      localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      // abaikan
    }
  };

  return (
    <button
      onClick={toggle}
      className={`rounded-full px-2 py-0.5 text-[11px] ${enabled ? "bg-close/20 text-close" : "bg-panel text-muted"}`}
      aria-pressed={enabled}
    >
      {enabled ? "☀ Layar tetap menyala" : "☀ Layar bisa mati"}
    </button>
  );
}
