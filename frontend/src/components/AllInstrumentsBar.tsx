"use client";

import { useEffect, useState } from "react";
import { endpoints } from "@/lib/api";
import { ACTION_STYLE } from "@/lib/signal";
import type { Action } from "@/lib/types";

type Progress =
  | { state: "antri" }
  | { state: "jalan" }
  | { state: "selesai"; action: Action }
  | { state: "gagal"; message: string };

interface Props {
  symbols: string[];
  onSelect: (symbol: string) => void;
  /** dipanggil setelah pengaturan / analisis berubah → muat ulang dashboard */
  onChanged: () => void;
}

/**
 * Kontrol untuk keempat instrumen sekaligus:
 * - "Pantau keempatnya": strategi menganalisis semua instrumen tiap 15 menit.
 * - "AI semua": AI Groq menganalisis semua instrumen bergantian (1 suara per instrumen).
 */
export function AllInstrumentsBar({ symbols, onSelect, onChanged }: Props) {
  const [watchAll, setWatchAll] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [progress, setProgress] = useState<Record<string, Progress>>({});
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    endpoints
      .watchAll()
      .then((r) => setWatchAll(r.enabled))
      .catch(() => setWatchAll(false));
  }, []);

  const toggleWatch = async () => {
    if (watchAll === null) return;
    setSaving(true);
    try {
      const r = await endpoints.setWatchAll(!watchAll);
      setWatchAll(r.enabled);
      onChanged();
    } catch (e) {
      setNote((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const runAll = async () => {
    setRunning(true);
    setNote(null);
    setProgress(Object.fromEntries(symbols.map((s) => [s, { state: "antri" } as Progress])));
    for (const [i, symbol] of symbols.entries()) {
      setProgress((p) => ({ ...p, [symbol]: { state: "jalan" } }));
      try {
        const res = await endpoints.runAi(symbol, 1);
        setProgress((p) => ({ ...p, [symbol]: { state: "selesai", action: res.card.action } }));
      } catch (e) {
        const message = (e as Error).message;
        setProgress((p) => ({ ...p, [symbol]: { state: "gagal", message } }));
        if (message.includes("kuota")) {
          // Kuota Groq habis: hentikan sisanya agar tidak membuang permintaan
          for (const rest of symbols.slice(i + 1)) {
            setProgress((p) => ({ ...p, [rest]: { state: "gagal", message: "dilewati" } }));
          }
          setNote(message);
          break;
        }
      }
    }
    setRunning(false);
    onChanged();
  };

  const hasProgress = Object.keys(progress).length > 0;

  return (
    <section className="surface space-y-2.5 rounded-2xl p-3">
      <div className="flex items-center gap-3">
        <button
          role="switch"
          aria-checked={!!watchAll}
          onClick={toggleWatch}
          disabled={watchAll === null || saving}
          className="flex min-w-0 flex-1 items-center gap-2.5 text-left disabled:opacity-60"
        >
          <span
            className={`relative h-6 w-11 shrink-0 rounded-full transition ${watchAll ? "bg-brand" : "bg-line"}`}
          >
            <span
              className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
                watchAll ? "left-[22px]" : "left-0.5"
              }`}
            />
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-bold">Pantau keempatnya</span>
            <span className="block text-[11px] leading-snug text-muted">
              {watchAll ? "Strategi menganalisis 4 instrumen tiap 15 menit" : "Hanya instrumen yang dibuka yang dianalisis"}
            </span>
          </span>
        </button>
        <button
          onClick={runAll}
          disabled={running || !symbols.length}
          className="shrink-0 rounded-xl bg-ai px-3 py-2 text-xs font-bold text-bg shadow-sm transition active:scale-95 disabled:opacity-50"
        >
          {running ? "Menganalisis…" : `🧠 AI semua (${symbols.length})`}
        </button>
      </div>

      {hasProgress && (
        <div className="grid grid-cols-4 gap-1.5">
          {symbols.map((s) => {
            const p = progress[s];
            if (!p) return null;
            let body: React.ReactNode;
            if (p.state === "antri") body = <span className="text-muted">antri</span>;
            else if (p.state === "jalan")
              body = (
                <span className="inline-flex items-center gap-1 text-ai">
                  <span className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-ai border-t-transparent" />
                  AI
                </span>
              );
            else if (p.state === "selesai") {
              const st = ACTION_STYLE[p.action];
              body = (
                <span className={`font-black ${st.text}`}>
                  {st.icon} {st.label}
                </span>
              );
            } else body = <span className="text-err" title={p.message}>gagal</span>;
            return (
              <button
                key={s}
                onClick={() => onSelect(s)}
                className="rounded-lg bg-panel-2 px-2 py-1.5 text-left text-[11px]"
                title={p.state === "gagal" ? p.message : undefined}
              >
                <span className="block font-semibold">{s}</span>
                {body}
              </button>
            );
          })}
        </div>
      )}
      {note && <p className="rounded-lg bg-sell/10 px-2.5 py-1.5 text-[11px] text-err">{note}</p>}
      {hasProgress && !running && (
        <p className="text-[11px] text-muted">
          AI semua memakai 1 suara per instrumen (lebih cepat, sedikit kurang teliti). Ketuk instrumen untuk melihat
          detailnya. Hasil AI bersifat eksperimen.
        </p>
      )}
    </section>
  );
}
