"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { endpoints } from "@/lib/api";
import { timeWIB } from "@/lib/format";
import type { PatternOut, PatternsResponse } from "@/lib/types";

const CONCLUSION_STYLE: Record<PatternsResponse["conclusion"]["bias"], string> = {
  BUY: "bg-buy/15 text-buy",
  SELL: "bg-sell/15 text-sell",
  MIXED: "bg-close/15 text-warn",
  NONE: "bg-panel-2 text-muted",
};

const CONCLUSION_LABEL: Record<PatternsResponse["conclusion"]["bias"], string> = {
  BUY: "▲ Condong naik",
  SELL: "▼ Condong turun",
  MIXED: "■ Campur",
  NONE: "Tidak ada pola",
};

/** Ringkasan cara mengenali setiap pola (ditampilkan di bagian "Panduan pola"). */
const GUIDE: [string, string][] = [
  ["Hammer", "Badan kecil di atas, sumbu bawah panjang, setelah harga turun → potensi naik"],
  ["Inverted Hammer", "Badan kecil di bawah, sumbu atas panjang, setelah turun → potensi naik"],
  ["Hanging Man", "Bentuk Hammer tetapi setelah harga naik → potensi turun"],
  ["Shooting Star", "Sumbu atas panjang setelah harga naik → potensi turun"],
  ["Morning Star", "Merah besar, candle kecil, lalu hijau menutup di atas tengah merah → naik"],
  ["Evening Star", "Hijau besar, candle kecil, lalu merah menutup di bawah tengah hijau → turun"],
  ["Bullish / Bearish Engulfing", "Candle kedua menelan penuh badan candle sebelumnya"],
  ["Piercing Line", "Hijau menutup di atas tengah candle merah sebelumnya → potensi naik"],
  ["Dark Cloud Cover", "Merah menutup di bawah tengah candle hijau sebelumnya → potensi turun"],
  ["Tweezer Bottom / Top", "Dua candle dengan low (atau high) hampir sama → pantulan"],
  ["Three White Soldiers", "Tiga hijau berturut-turut dengan badan kuat → tekanan beli"],
  ["Three Black Crows", "Tiga merah berturut-turut dengan badan kuat → tekanan jual"],
  ["Spinning Top", "Badan kecil, dua sumbu panjang → pasar ragu-ragu"],
];

function Strength({ value }: { value: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`kekuatan ${value} dari 3`}>
      {[1, 2, 3].map((i) => (
        <span key={i} className={`h-1.5 w-1.5 rounded-full ${i <= value ? "bg-fg" : "bg-line"}`} />
      ))}
    </span>
  );
}

function PatternRow({ p }: { p: PatternOut }) {
  const color = p.bias > 0 ? "text-buy" : p.bias < 0 ? "text-sell" : "text-warn";
  const icon = p.bias > 0 ? "▲" : p.bias < 0 ? "▼" : "◆";
  return (
    <li className="space-y-0.5">
      <div className="flex items-center gap-2 text-sm">
        <span className={`font-bold ${color}`}>
          {icon} {p.name}
        </span>
        {p.bias !== 0 && <Strength value={p.strength} />}
        <span className="text-[11px] text-muted">{p.strength_text}</span>
      </div>
      <p className="text-[11px] leading-snug text-muted">
        {p.meaning}; {p.note}.
      </p>
    </li>
  );
}

/**
 * Pola candlestick (Hammer, Morning Star, Engulfing, dst.) pada candle tertutup terakhir
 * di M15, H1 dan H4. Kekuatan: +1 di area support/resistance, +1 searah tren.
 */
export function PatternPanel({ symbol, reloadKey }: { symbol: string; reloadKey: number }) {
  const [data, setData] = useState<PatternsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    endpoints
      .patterns(symbol)
      .then((res) => {
        if (!active) return;
        setData(res);
        setError(null);
      })
      .catch((e: Error) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [symbol, reloadKey]);

  return (
    <section className="surface space-y-3 rounded-2xl p-3">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1 text-sm font-bold">🕯️ Pola Candlestick</div>
        {data && (
          <span className={`rounded-lg px-2 py-1 text-xs font-bold ${CONCLUSION_STYLE[data.conclusion.bias]}`}>
            {CONCLUSION_LABEL[data.conclusion.bias]}
          </span>
        )}
      </div>

      {error && <p className="text-xs text-err">{error}</p>}
      {!data && !error && <div className="h-20 animate-pulse rounded-xl bg-panel-2" />}

      {data && (
        <>
          <p className="text-xs text-fg-soft">{data.conclusion.text}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            {data.timeframes.map((tf) => (
              <div key={tf.timeframe} className="rounded-xl bg-panel-2 p-2.5">
                <div className="mb-1.5 flex items-center justify-between text-[11px] text-muted">
                  <span className="font-bold text-fg">{tf.timeframe}</span>
                  <span>
                    tren {tf.trend}
                    {tf.candle_time != null && ` · candle ${timeWIB(tf.candle_time)}`}
                  </span>
                </div>
                {tf.patterns.length ? (
                  <ul className="space-y-2">
                    {tf.patterns.map((p) => (
                      <PatternRow key={p.name} p={p} />
                    ))}
                  </ul>
                ) : (
                  <p className="text-[11px] text-muted">Tidak ada pola khusus.</p>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      <details className="text-[11px] text-muted">
        <summary className="cursor-pointer font-semibold text-fg-soft">Ringkasan pola</summary>
        <ul className="mt-2 space-y-1">
          {GUIDE.map(([name, text]) => (
            <li key={name}>
              <b className="text-fg-soft">{name}</b>: {text}
            </li>
          ))}
        </ul>
        <p className="mt-2">
          Kekuatan ●●● = di area support/resistance <i>dan</i> searah tren. Pola hanyalah petunjuk, bukan
          kepastian; tunggu candle berikutnya sebagai konfirmasi. Di grafik, tombol POLA menampilkan pola
          kuat saja (★).{" "}
          <Link href="/panduan#pola" className="text-brand underline">
            Buka panduan lengkap
          </Link>
        </p>
      </details>
    </section>
  );
}
