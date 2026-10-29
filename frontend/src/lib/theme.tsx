"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type ThemeChoice = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

const STORAGE_KEY = "signalflow:theme";
const THEME_COLOR = { dark: "#0b0e11", light: "#f3f5f8" } as const;

/**
 * Skrip kecil yang dijalankan sebelum halaman tampil (di <head>) agar tidak ada kedip warna
 * saat membuka aplikasi: membaca pilihan tersimpan atau preferensi sistem.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var c=localStorage.getItem("${STORAGE_KEY}")||"system";var t=c==="system"?(matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"):c;document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme="dark";}})();`;

interface ThemeContextValue {
  choice: ThemeChoice;
  resolved: ResolvedTheme;
  setChoice: (choice: ThemeChoice) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function systemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>("system");
  const [resolved, setResolved] = useState<ResolvedTheme>("dark");

  useEffect(() => {
    let stored: ThemeChoice = "system";
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw === "dark" || raw === "light" || raw === "system") stored = raw;
    } catch {
      // localStorage tidak tersedia
    }
    setChoiceState(stored);
  }, []);

  // Terapkan tema & ikuti perubahan tema sistem bila memilih "system"
  useEffect(() => {
    const apply = () => {
      const next = choice === "system" ? systemTheme() : choice;
      setResolved(next);
      document.documentElement.dataset.theme = next;
      document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[next]);
    };
    apply();
    if (choice !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: light)");
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [choice]);

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // abaikan
    }
  }, []);

  const toggle = useCallback(() => setChoice(resolved === "dark" ? "light" : "dark"), [resolved, setChoice]);

  return <ThemeContext.Provider value={{ choice, resolved, setChoice, toggle }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme harus dipakai di dalam ThemeProvider");
  return ctx;
}

/** Warna tema saat ini dari variabel CSS (untuk grafik canvas yang tidak memakai kelas CSS). */
export function readPalette() {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    bg: v("--bg"),
    panel: v("--panel"),
    grid: v("--chart-grid"),
    line: v("--line"),
    text: v("--muted"),
    fg: v("--fg"),
    up: v("--buy"),
    down: v("--sell"),
    close: v("--close"),
    ai: v("--ai"),
  };
}
