"use client";

import { useEffect, useState } from "react";
import { endpoints } from "@/lib/api";
import type { LiveStats, PredictionSummary } from "@/lib/types";

export const PERIODS = [
  { days: 1, label: "1 hari" },
  { days: 7, label: "1 minggu" },
  { days: 30, label: "1 bulan" },
  { days: 365, label: "1 tahun" },
];

const signed = (v: number, digits = 1) => `${v > 0 ? "+" : ""}${v.toFixed(digits)}`;
const tone = (v: number) => (v > 0 ? "text-buy" : v < 0 ? "text-sell" : "text-fg");

interface Row {
  key: string;
  title: string;
  /** jumlah yang sudah ada hasilnya */
  done: number;
  hits: number;
  pips: number;
  /** pertumbuhan modal (%) dengan risiko per sinyal dari Pengaturan; null = tidak berlaku */
  growth: number | null;
}

function fromStats(key: string, title: string, s: LiveStats): Row {
  const m = s.overall;
  return { key, title, done: m.trades, hits: m.wins, pips: m.net_pips, growth: m.return_pct };
}

function Card({ r }: { r: Row }) {
  const rate = r.done ? (r.hits / r.done) * 100 : null;
  return (
    <div className="rounded-xl bg-bg/60 p-3">
      <div className="text-xs font-semibold text-muted">{r.title}</div>
      {rate == null ? (
        <p className="mt-2 text-sm text-muted">Belum ada hasil</p>
      ) : (
        <>
          <div className="mt-1 flex items-baseline gap-1">
            <span className={`tabular text-2xl font-black ${rate >= 50 ? "text-buy" : "text-sell"}`}>
              {rate.toFixed(0)}%
            </span>
            <span className="text-xs text-muted">tepat</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-sell/30">
            <div className="h-full bg-buy" style={{ width: `${rate}%` }} />
          </div>
          <div className="tabular mt-2 text-xs text-muted">
            {r.hits} dari {r.done} untung
          </div>
          {r.growth != null && (
            <div className="tabular mt-1 text-sm">
              Pertumbuhan <b className={tone(r.growth)}>{signed(r.growth, 1)}%</b>
            </div>
          )}
          <div className={`tabular text-xs ${tone(r.pips)}`}>{signed(r.pips, 0)} pip</div>
        </>
      )}
    </div>
  );
}

/** Ketepatan Strategi, AI, dan prediksi pola dalam satu periode, berdampingan. */
export function AccuracySummary({
  days,
  onDays,
  refreshKey,
}: {
  days: number;
  onDays: (days: number) => void;
  refreshKey: number;
}) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [risk, setRisk] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      endpoints.stats(days, "rule"),
      endpoints.stats(days, "ai"),
      endpoints.predictions(undefined, undefined, days),
    ])
      .then(([rule, ai, pred]: [LiveStats, LiveStats, PredictionSummary]) => {
        if (cancelled) return;
        setRows([
          fromStats("rule", "Strategi", rule),
          fromStats("ai", "AI Groq", ai),
          { key: "pattern", title: "Prediksi pola", done: pred.done, hits: pred.hits, pips: pred.pips, growth: null },
        ]);
        setRisk(rule.risk_percent);
        setError(null);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [days, refreshKey]);

  const label = PERIODS.find((p) => p.days === days)?.label ?? `${days} hari`;
  const best = rows
    ?.filter((r) => r.done > 0)
    .sort((a, b) => b.hits / b.done - a.hits / a.done)[0];

  return (
    <section className="surface space-y-3 rounded-2xl p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">Ketepatan {label} terakhir</h2>
        <div className="flex gap-1 rounded-lg bg-bg/60 p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.days}
              onClick={() => onDays(p.days)}
              className={`rounded-md px-2.5 py-1 text-xs font-semibold ${p.days === days ? "bg-fg text-bg" : "text-muted"}`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="text-sm text-sell">{error}</p>}
      {rows && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {rows.map((r) => (
            <Card key={r.key} r={r} />
          ))}
        </div>
      )}
      {best && (
        <p className="text-sm text-fg-soft">
          Paling tepat {label} terakhir: <b>{best.title}</b> ({((best.hits / best.done) * 100).toFixed(0)}% dari{" "}
          {best.done}).
          {best.done < 20 && " Hasilnya masih sedikit, jadi belum bisa dijadikan pegangan."}
        </p>
      )}
      <p className="text-[11px] text-muted">
        Tepat = sinyal/prediksi yang selesai dengan untung setelah spread. Pertumbuhan = perubahan modal bila
        setiap sinyal memakai risiko {risk ?? "—"}% (Pengaturan). Prediksi pola tidak memakai SL, jadi hanya
        dihitung dalam pip.
      </p>
    </section>
  );
}
