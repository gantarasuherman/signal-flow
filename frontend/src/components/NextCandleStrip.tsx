"use client";

import { useEffect, useState } from "react";
import { endpoints } from "@/lib/api";
import { timeWIB } from "@/lib/format";
import { TF_SECONDS, type FormingResponse, type Timeframe } from "@/lib/types";

/** Pola candle berjalan dibaca ulang tiap 15 detik (mengikuti harga live). */
const POLL_MS = 15_000;

function countdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
}

function holdText(hold: number, tf: Timeframe): string {
  const minutes = (hold * TF_SECONDS[tf]) / 60;
  if (minutes < 60) return `${minutes} menit`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} jam ${m} menit` : `${h} jam`;
}

/**
 * Prediksi SEMENTARA candle berikutnya dari pola yang sedang terbentuk di candle berjalan
 * (dibaca seolah candle tutup di harga sekarang). Hanya pola terbukti di histori yang memberi
 * arah; bisa berubah sampai candle tutup, lalu menjadi titik ▶ final di grafik.
 */
export function NextCandleStrip({
  symbol,
  timeframe,
  reloadKey,
}: {
  symbol: string;
  timeframe: Timeframe | null;
  reloadKey: number;
}) {
  const [data, setData] = useState<FormingResponse | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);

  useEffect(() => {
    if (!timeframe) return;
    let active = true;
    const load = () =>
      endpoints
        .formingPattern(symbol, timeframe)
        .then((r) => active && setData(r))
        .catch(() => undefined);
    void load();
    const id = setInterval(load, POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [symbol, timeframe, reloadKey]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  if (!timeframe || !data || data.timeframe !== timeframe) return null;

  if (!data.live || data.candle_end == null || data.candle_start == null || data.next_end == null) {
    return (
      <div className="surface rounded-2xl px-3 py-2 text-xs text-muted">
        ⏳ Candle berikutnya ({timeframe}): {data.note}
      </div>
    );
  }

  const left = data.candle_end - now;
  const progress = Math.min(1, Math.max(0, (now - data.candle_start) / (data.candle_end - data.candle_start)));
  const p = data.prediction;
  const buy = p?.direction === "BUY";
  const forming = data.patterns.filter((x) => x.bias !== 0).map((x) => x.name);
  const box = p ? (buy ? "border-buy/40 bg-buy/10" : "border-sell/40 bg-sell/10") : "border-line bg-panel";

  return (
    <section className={`space-y-1.5 rounded-2xl border px-3 py-2.5 ${box}`}>
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold tracking-widest text-muted">CANDLE BERIKUTNYA · {timeframe}</span>
        <span className="tabular ml-auto text-[11px] text-muted">
          {timeWIB(data.candle_end)}–{timeWIB(p ? p.close_at : data.next_end)} WIB
        </span>
      </div>
      {p && (
        <div className="flex items-baseline gap-2">
          <span className={`text-xl font-black ${buy ? "text-buy" : "text-sell"}`}>{buy ? "▲ BUY" : "▼ SELL"}</span>
          <span className="text-xs font-semibold text-fg-soft">
            sementara · {p.pattern}, benar {Math.round(p.chance * 100)}% dari {p.samples} kejadian
          </span>
        </div>
      )}
      {p ? (
        <div className="rounded-lg bg-close/10 px-2.5 py-1.5 text-xs leading-snug">
          <b className="text-warn">⏹ CLOSE {timeWIB(p.close_at)} WIB</b>{" "}
          <span className="text-fg-soft">
            (tahan {p.hold} candle = {holdText(p.hold, timeframe)})
          </span>
          <span className="block text-muted">
            {p.avg_pips != null && p.win_rate != null
              ? `Di histori, menutup di sini memberi rata-rata untung terbesar: +${p.avg_pips.toFixed(1)} pip per transaksi setelah spread, untung ${Math.round(p.win_rate * 100)}% kejadian.`
              : "Tidak ada lama tahan yang rata-ratanya untung setelah spread — kalau ikut, CLOSE cepat di akhir candle berikutnya."}
          </span>
        </div>
      ) : (
        <div className="text-sm font-semibold text-fg-soft">
          Belum ada prediksi
          {forming.length > 0 && (
            <span className="font-normal text-muted"> — {forming.join(", ")} terbentuk tetapi belum terbukti</span>
          )}
        </div>
      )}
      <div className="flex h-1 overflow-hidden rounded-full bg-line">
        <div className="bg-fg-soft transition-[width] duration-1000" style={{ width: `${progress * 100}%` }} />
      </div>
      <p className="tabular text-[11px] leading-snug text-muted">
        {left > 0 ? (
          <>
            Candle berjalan tutup {timeWIB(data.candle_end)} (<b className="text-fg-soft">{countdown(left)}</b> lagi).{" "}
            {p
              ? `Bila bentuknya bertahan sampai tutup: ${p.direction} di awal candle berikutnya, CLOSE ${timeWIB(p.close_at)}.`
              : "Arah muncul di sini bila pola terbukti terbentuk."}
          </>
        ) : (
          "Candle sudah tutup — memperbarui…"
        )}
      </p>
    </section>
  );
}
