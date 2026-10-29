"use client";

import { formatPrice, timeWIB } from "@/lib/format";
import { ACTION_STYLE, liveEntryState } from "@/lib/signal";
import type { InstrumentCard } from "@/lib/types";

/**
 * Bilah instruksi di atas grafik: satu kalimat yang langsung bisa diikuti
 * (BUY sekarang / jangan masuk / tutup posisi / tunggu).
 */
const SOURCE_LABEL = { rule: "STRATEGI", ai: "AI GROQ" } as const;

export function SignalStrip({ card, livePrice }: { card: InstrumentCard; livePrice: number | null }) {
  const { signal, instrument } = card;
  const digits = instrument.digits;
  const style = ACTION_STYLE[card.action];

  let headline: string;
  let detail: React.ReactNode = null;

  if (card.action === "CLOSE") {
    headline = `Tutup posisi ${signal?.closes_action ?? ""} sekarang`;
    detail = signal?.close_reason;
  } else if ((card.action === "BUY" || card.action === "SELL") && signal) {
    const { state } = liveEntryState(signal, livePrice ?? signal.current_price);
    if (state === "VALID") {
      headline = `${card.action} sekarang`;
      detail = (
        <span className="tabular">
          Entry {formatPrice(signal.entry, digits)} · <span className="text-sell">SL {formatPrice(signal.stop_loss, digits)}</span>{" "}
          · <span className="text-buy">TP {formatPrice(signal.take_profit, digits)}</span>
          {signal.suggested_lot ? ` · ${signal.suggested_lot.toFixed(2)} lot` : ""}
          {signal.entry_valid_until && ` · berlaku s/d ${timeWIB(signal.entry_valid_until)}`}
        </span>
      );
    } else {
      headline = `${card.action} kedaluwarsa — jangan masuk`;
      detail = "Bila sudah terlanjur masuk: biarkan SL/TP bekerja, tunggu CLOSE.";
    }
  } else if (card.analysis?.details?.idle) {
    headline = "Menganalisis…";
    detail = "Instrumen ini baru dipilih; data & sinyal disiapkan dalam beberapa detik.";
  } else if (!instrument.market_open) {
    headline = "Pasar tutup";
    detail = "Tidak ada sinyal sampai pasar buka kembali.";
  } else {
    headline = "Tunggu, jangan buka posisi";
    detail = card.analysis?.reasons[0];
  }

  return (
    <div
      className={`surface relative flex items-center gap-3 overflow-hidden rounded-2xl py-3 pl-4 pr-3 ${
        card.is_new_event && card.action !== "WAIT" ? `animate-pulse ring-2 ring-offset-2 ring-offset-bg ${style.ring}` : ""
      }`}
    >
      {/* aksen warna aksi: garis kiri + gradasi */}
      <span className={`absolute inset-y-0 left-0 w-1.5 ${style.bar}`} />
      <span className={`pointer-events-none absolute inset-0 bg-gradient-to-r ${style.grad} to-transparent`} />
      <div className="relative w-[4.75rem] shrink-0 text-center">
        <div className={`text-[9px] font-bold tracking-widest ${card.source === "ai" ? "text-ai" : "text-muted"}`}>
          {SOURCE_LABEL[card.source]}
        </div>
        <div className={`flex items-center justify-center gap-0.5 text-[1.7rem] font-black leading-none ${style.text}`}>
          <span className="text-sm">{style.icon}</span>
          {style.label}
        </div>
      </div>
      <div className="relative min-w-0 flex-1">
        <div className="font-bold leading-tight">{headline}</div>
        {detail && <div className="mt-0.5 line-clamp-2 text-xs leading-snug text-fg-soft">{detail}</div>}
      </div>
    </div>
  );
}
