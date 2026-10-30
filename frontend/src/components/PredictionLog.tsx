"use client";

import { useEffect, useState } from "react";
import { endpoints } from "@/lib/api";
import { dateTimeWIB, timeWIB } from "@/lib/format";
import type { PredictionSummary } from "@/lib/types";

const pipsText = (p: number) => `${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(p).toFixed(1)} pip`;
const pct = (hits: number, done: number) => (done ? `${Math.round((hits / done) * 100)}%` : "–");

/** Kumpulan prediksi kecil masih bisa terlihat bagus/buruk karena kebetulan. */
const MIN_RELIABLE = 30;

/**
 * Uji maju prediksi pola: setiap prediksi dicatat saat pola muncul (sebelum hasilnya
 * diketahui), lalu dinilai setelah candle tutup. Ukuran jujur untuk titik prediksi di grafik.
 */
export function PredictionLog() {
  const [data, setData] = useState<PredictionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    endpoints
      .predictions()
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="text-sm text-err">{error}</p>;
  if (!data) return <div className="h-32 animate-pulse rounded-2xl bg-panel" />;

  return (
    <div className="space-y-3">
      <section className="surface space-y-2 rounded-2xl p-4">
        <h2 className="font-bold">📒 Uji maju prediksi pola</h2>
        <p className="text-xs leading-snug text-muted">
          Setiap titik ▶ BUY/SELL dari pola dicatat <b>saat muncul</b>, lalu dinilai setelah candle-nya tutup
          (bersih setelah spread). Prediksi yang terlambat dicatat tidak dihitung. Inilah ukuran jujur apakah titik
          prediksi di grafik benar-benar menguntungkan.
          {data.since && ` Mulai dicatat ${dateTimeWIB(data.since)} WIB.`}
        </p>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-xl bg-panel-2 p-2">
            <div className="tabular text-xl font-bold">{data.done}</div>
            <div className="text-[11px] text-muted">selesai</div>
          </div>
          <div className="rounded-xl bg-panel-2 p-2">
            <div className="tabular text-xl font-bold">{pct(data.hits, data.done)}</div>
            <div className="text-[11px] text-muted">benar</div>
          </div>
          <div className="rounded-xl bg-panel-2 p-2">
            <div className={`tabular text-xl font-bold ${data.pips > 0 ? "text-buy" : data.pips < 0 ? "text-sell" : ""}`}>
              {pipsText(data.pips)}
            </div>
            <div className="text-[11px] text-muted">total</div>
          </div>
        </div>
        {data.pending > 0 && <p className="text-xs text-muted">{data.pending} prediksi menunggu candle tutup.</p>}
        {data.done < MIN_RELIABLE && (
          <p className="rounded-lg bg-close/10 px-2.5 py-1.5 text-xs text-warn">
            Baru {data.done} prediksi selesai. Butuh minimal {MIN_RELIABLE} sebelum hasilnya bisa dipercaya; jangan
            dulu memakai uang sungguhan.
          </p>
        )}
      </section>

      {data.groups.length > 0 && (
        <section className="surface rounded-2xl p-4">
          <h3 className="mb-2 text-sm font-bold">Per instrumen & timeframe</h3>
          <table className="tabular w-full text-sm">
            <thead className="text-left text-[11px] text-muted">
              <tr>
                <th className="py-1 font-medium">Grafik</th>
                <th className="py-1 text-right font-medium">Selesai</th>
                <th className="py-1 text-right font-medium">Benar</th>
                <th className="py-1 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.groups.map((g) => (
                <tr key={`${g.symbol}-${g.timeframe}`} className="border-t border-line">
                  <td className="py-1.5">
                    {g.symbol} <span className="text-muted">{g.timeframe}</span>
                  </td>
                  <td className="py-1.5 text-right">{g.done}</td>
                  <td className="py-1.5 text-right">{pct(g.hits, g.done)}</td>
                  <td className={`py-1.5 text-right ${g.pips > 0 ? "text-buy" : g.pips < 0 ? "text-sell" : ""}`}>
                    {pipsText(g.pips)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="surface rounded-2xl p-4">
        <h3 className="mb-2 text-sm font-bold">Prediksi terbaru</h3>
        {data.recent.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">
            Belum ada prediksi tercatat. Prediksi muncul hanya saat pola terbukti terbentuk; buka grafik atau nyalakan
            &quot;Pantau keempatnya&quot; agar lebih banyak timeframe ikut tercatat.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {data.recent.map((p) => (
              <li key={p.id} className="flex items-center gap-2 py-2 text-sm">
                <span className={`w-12 font-bold ${p.direction > 0 ? "text-buy" : "text-sell"}`}>
                  {p.direction > 0 ? "▲ BUY" : "▼ SELL"}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate">
                    {p.symbol} <span className="text-muted">{p.timeframe}</span> · {p.pattern}
                  </span>
                  <span className="tabular block text-[11px] text-muted">
                    {dateTimeWIB(p.entry_time)} → CLOSE {timeWIB(p.close_time)} · histori {Math.round(p.chance * 100)}%
                  </span>
                </span>
                <span
                  className={`tabular text-right text-xs font-semibold ${
                    p.result_pips == null ? "text-muted" : p.result_pips > 0 ? "text-buy" : "text-sell"
                  }`}
                >
                  {p.status === "open"
                    ? "menunggu"
                    : p.status === "no_data"
                      ? "tanpa data"
                      : `${(p.result_pips ?? 0) > 0 ? "✓" : "✗"} ${pipsText(p.result_pips ?? 0)}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
