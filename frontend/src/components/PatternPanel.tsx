"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { endpoints } from "@/lib/api";
import type { PatternOut, PatternsResponse, Timeframe } from "@/lib/types";

/** Sama dengan MIN_EDGE di backend: di bawah ini pola dianggap seperti lempar koin. */
const EDGE = 0.55;
const TF_MINUTES: Record<Timeframe, number> = { M1: 1, M5: 5, M15: 15, H1: 60, H4: 240 };

/** "4 candle" → durasi nyata sesuai timeframe, mis. M15 → 1 jam, H4 → 16 jam. */
function horizonText(tf: Timeframe, candles: number): string {
  const minutes = TF_MINUTES[tf] * candles;
  return minutes < 60 ? `${minutes} menit` : `${minutes / 60} jam`;
}

/** Meter kemungkinan: berapa dari 100 kali harga naik vs turun setelah pola. */
function UpDownMeter({ up, size = "md" }: { up: number; size?: "md" | "sm" }) {
  const upPct = Math.round(up * 100);
  const downPct = 100 - upPct;
  const text = size === "md" ? "text-sm" : "text-[11px]";
  return (
    <div className="space-y-1">
      <div className={`tabular flex justify-between font-bold ${text}`}>
        <span className={upPct > downPct ? "text-buy" : "text-muted"}>▲ Naik {upPct}%</span>
        <span className={downPct > upPct ? "text-sell" : "text-muted"}>Turun {downPct}% ▼</span>
      </div>
      <div className={`flex overflow-hidden rounded-full ${size === "md" ? "h-2.5" : "h-1.5"}`}>
        <div className="bg-buy" style={{ width: `${upPct}%` }} />
        <div className="bg-sell" style={{ width: `${downPct}%` }} />
      </div>
    </div>
  );
}

/** Kekuatan kecondongan; hanya "cukup/kuat" bila backend menyimpulkan BUY/SELL (lolos uji). */
function leanText(bias: PatternsResponse["conclusion"]["bias"], chance: number): string {
  if (bias !== "BUY" && bias !== "SELL") return "lemah — belum meyakinkan secara statistik";
  return chance >= 0.6 ? "kuat" : "cukup";
}

const VERDICT_STYLE = {
  BUY: { box: "bg-buy/10 border-buy/30", icon: "▲", tone: "text-buy" },
  SELL: { box: "bg-sell/10 border-sell/30", icon: "▼", tone: "text-sell" },
  MIXED: { box: "bg-panel-2 border-line", icon: "≈", tone: "text-warn" },
  NONE: { box: "bg-panel-2 border-line", icon: "–", tone: "text-muted" },
} as const;

/** Kesimpulan dalam bahasa sehari-hari + apa yang sebaiknya dilakukan. */
function Verdict({ conclusion }: { conclusion: PatternsResponse["conclusion"] }) {
  const { bias, probability, direction } = conclusion;
  const up = probability != null && direction ? (direction === "naik" ? probability : 1 - probability) : null;
  const pct = probability != null ? Math.round(probability * 100) : null;
  let title: string;
  let detail: string;
  let action: string;
  if ((bias === "BUY" || bias === "SELL") && pct != null) {
    const word = bias === "BUY" ? "NAIK" : "TURUN";
    title = `Harga cenderung ${word}`;
    detail = `Setelah pola seperti ini, harga ${word.toLowerCase()} ${pct} dari 100 kali (${conclusion.samples} kejadian).`;
    action = `Bisa jadi konfirmasi ${bias} bila sinyal strategi/AI juga ${bias}. Tetap pasang SL.`;
  } else if (bias === "MIXED" && pct != null && direction) {
    title = `Sedikit condong ${direction.toUpperCase()} (lemah)`;
    detail = `Setelah pola seperti ini, harga ${direction} ${pct} dari 100 kali (${conclusion.samples} kejadian) — belum cukup untuk diandalkan.`;
    action = "Jangan masuk hanya karena pola ini.";
  } else if (bias === "NONE") {
    title = "Tidak ada pola penting";
    detail = "Bentuk candle terakhir tidak memberi petunjuk arah.";
    action = "Ikuti sinyal strategi/AI seperti biasa.";
  } else {
    // Kesimpulan tanpa data peluang (mis. pola baru / histori pendek): pakai teks backend
    title = bias === "BUY" ? "Condong naik (belum teruji)" : bias === "SELL" ? "Condong turun (belum teruji)" : "Sinyal pola bertentangan";
    detail = conclusion.text;
    action = "Anggap sebagai petunjuk lemah; tunggu konfirmasi.";
  }
  const st = VERDICT_STYLE[bias];
  return (
    <div className={`flex gap-3 rounded-xl border p-3 ${st.box}`}>
      <span className={`text-2xl font-black leading-none ${st.tone}`} aria-hidden>
        {st.icon}
      </span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className={`font-bold ${bias === "BUY" || bias === "SELL" ? st.tone : ""}`}>{title}</div>
        <p className="text-xs leading-snug text-fg-soft">{detail}</p>
        {up != null && probability != null && (
          <div className="pt-1.5">
            <UpDownMeter up={up} />
            <p className="mt-1 text-[11px] text-muted">Kecondongan: {leanText(bias, probability)}</p>
          </div>
        )}
        <p className="pt-1 text-xs font-semibold leading-snug">→ {action}</p>
      </div>
    </div>
  );
}

type Reliability = { label: string; className: string };

function reliability(p: PatternOut): Reliability {
  if (p.bias === 0) return { label: "Pasar ragu", className: "bg-close/15 text-warn" };
  if (p.probability == null) return { label: "Data sedikit", className: "bg-panel-2 text-muted" };
  const leaning = p.probability >= EDGE || p.probability <= 1 - EDGE;
  if (leaning && !p.reliable) return { label: "Condong, data terbatas", className: "bg-panel-2 text-fg-soft" };
  if (p.reliable && p.probability >= 0.5)
    return { label: "Sering benar", className: p.bias > 0 ? "bg-buy/15 text-buy" : "bg-sell/15 text-sell" };
  if (p.reliable) return { label: "Sering gagal", className: "bg-close/15 text-warn" };
  return { label: "Seperti lempar koin", className: "bg-panel-2 text-muted" };
}

function PatternItem({ p, tf, symbol, horizon }: { p: PatternOut; tf: Timeframe; symbol: string; horizon: number }) {
  const color = p.bias > 0 ? "text-buy" : p.bias < 0 ? "text-sell" : "text-warn";
  const icon = p.bias > 0 ? "▲" : p.bias < 0 ? "▼" : "◆";
  const rel = reliability(p);
  const word = p.bias > 0 ? "naik" : "turun";
  const opposite = p.bias > 0 ? "turun" : "naik";
  const span = horizonText(tf, horizon);
  let stat: string | null = null;
  if (p.bias !== 0 && p.probability != null) {
    const pct = Math.round(p.probability * 100);
    stat =
      p.probability <= 1 - EDGE
        ? `Dari ${p.samples} kali muncul di ${symbol} ${tf}, harga justru lebih sering ${opposite} (${100 - pct} dari 100) dalam ${span} berikutnya.`
        : `Dari ${p.samples} kali muncul di ${symbol} ${tf}, harga ${word} ${pct} dari 100 kali dalam ${span} berikutnya.`;
  } else if (p.bias !== 0) {
    stat = `Baru ${p.samples} kali muncul di ${symbol} ${tf} — belum cukup untuk dinilai.`;
  }
  return (
    <li className="space-y-1 rounded-xl bg-panel-2 p-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`font-bold ${color}`}>
          {icon} {p.name}
        </span>
        <span className="rounded bg-bg/60 px-1.5 text-[10px] font-bold text-fg-soft">{tf}</span>
        <span className={`ml-auto rounded-md px-1.5 py-0.5 text-[11px] font-bold ${rel.className}`}>{rel.label}</span>
      </div>
      <p className="text-sm leading-snug">{p.meaning.charAt(0).toUpperCase() + p.meaning.slice(1)}.</p>
      {p.bias !== 0 && p.probability != null && (
        <UpDownMeter up={p.bias > 0 ? p.probability : 1 - p.probability} size="sm" />
      )}
      {stat && <p className="text-xs leading-snug text-fg-soft">{stat}</p>}
      <p className="text-[11px] leading-snug text-muted">Konteks: {p.note}.</p>
    </li>
  );
}

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

/**
 * Pola candlestick (Hammer, Morning Star, Engulfing, dst.) pada candle tertutup terakhir
 * di M1–H4. Kekuatan: +1 di area support/resistance, +1 searah tren. Peluang = seberapa
 * sering pola itu diikuti gerakan searah di histori instrumen ini → kemungkinan BUY / SELL.
 * Dimuat ulang setiap timeframe grafik (`activeTf`) berganti.
 */
export function PatternPanel({
  symbol,
  reloadKey,
  activeTf,
}: {
  symbol: string;
  reloadKey: number;
  activeTf: Timeframe | null;
}) {
  const [data, setData] = useState<PatternsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeTf) return; // tunggu grafik menentukan timeframe-nya
    let active = true;
    endpoints
      .patterns(symbol, activeTf)
      .then((res) => {
        if (!active) return;
        setData(res);
        setError(null);
      })
      .catch((e: Error) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [symbol, reloadKey, activeTf]);

  const found = data?.timeframes.flatMap((tf) => tf.patterns.map((p) => ({ p, tf: tf.timeframe }))) ?? [];
  const quiet = data?.timeframes.filter((tf) => tf.up_to_date && !tf.patterns.length).map((tf) => tf.timeframe) ?? [];
  const stale = data?.timeframes.filter((tf) => !tf.up_to_date).map((tf) => tf.timeframe) ?? [];

  return (
    <section className="surface space-y-3 rounded-2xl p-3">
      <div>
        <div className="text-sm font-bold">🕯️ Pola Candlestick</div>
        <p className="text-[11px] text-muted">
          Bentuk candle terakhir di tiap timeframe, dan seberapa sering bentuk itu benar di histori {symbol}.
        </p>
      </div>

      {error && <p className="text-xs text-err">{error}</p>}
      {!data && !error && <div className="h-20 animate-pulse rounded-xl bg-panel-2" />}

      {data && (
        <>
          <Verdict conclusion={data.conclusion} />
          {found.length > 0 && (
            <ul className="space-y-2">
              {found.map(({ p, tf }) => (
                <PatternItem key={`${tf}-${p.name}`} p={p} tf={tf} symbol={symbol} horizon={data.horizon} />
              ))}
            </ul>
          )}
          {(quiet.length > 0 || stale.length > 0) && (
            <div className="space-y-0.5 text-[11px] text-muted">
              {quiet.length > 0 && <p>Tidak ada pola di: {quiet.join(", ")}.</p>}
              {stale.length > 0 && (
                <p>
                  Belum diperbarui: {stale.join(", ")} — pilih timeframe itu di grafik untuk menilainya.
                </p>
              )}
            </div>
          )}
        </>
      )}

      <details className="text-[11px] text-muted">
        <summary className="cursor-pointer font-semibold text-fg-soft">Cara membaca panel ini</summary>
        <ul className="mt-2 list-disc space-y-1 pl-4">
          <li>
            <b className="text-fg-soft">Pola candlestick</b> = bentuk 1–3 candle terakhir yang sering dianggap tanda harga
            akan berbalik atau berlanjut.
          </li>
          <li>
            <b className="text-fg-soft">Naik % / Turun %</b>: dari histori, berapa kali dari 100 harga naik atau turun
            setelah pola ini muncul.
          </li>
          <li>
            <b className="text-fg-soft">Sering benar</b>: harga bergerak sesuai pola ≥55 dari 100 kali dan datanya
            cukup banyak. <b className="text-fg-soft">Sering gagal</b>: harga justru lebih sering ke arah sebaliknya.{" "}
            <b className="text-fg-soft">Condong, data terbatas</b>: persentasenya menjanjikan tetapi kejadiannya masih
            sedikit. <b className="text-fg-soft">Seperti lempar koin</b>: 46–54 dari 100 — abaikan.
          </li>
          <li>
            <b className="text-fg-soft">Konteks</b>: pola lebih bisa dipercaya bila muncul di area support/resistance dan
            searah tren.
          </li>
          <li>Pola hanyalah petunjuk tambahan. Jangan buka posisi hanya karena pola; ikuti sinyal dan pasang SL.</li>
        </ul>
        <p className="mt-2 font-semibold text-fg-soft">Bentuk tiap pola</p>
        <ul className="mt-1 space-y-1">
          {GUIDE.map(([name, text]) => (
            <li key={name}>
              <b className="text-fg-soft">{name}</b>: {text}
            </li>
          ))}
        </ul>
        <p className="mt-2">
          Di grafik, tombol POLA menandai pola kuat (titik).{" "}
          <Link href="/panduan#pola" className="text-brand underline">
            Lihat pola paling berpotensi di Panduan
          </Link>
        </p>
      </details>
    </section>
  );
}
