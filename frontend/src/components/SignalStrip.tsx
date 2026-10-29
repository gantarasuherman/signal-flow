"use client";

import { formatPrice, timeWIB } from "@/lib/format";
import { ACTION_STYLE, liveEntryState } from "@/lib/signal";
import type { InstrumentCard } from "@/lib/types";

/**
 * Bilah instruksi di atas grafik: satu kalimat yang langsung bisa diikuti
 * (BUY sekarang / jangan masuk / tutup posisi / tunggu).
 */
const SOURCE_LABEL = { rule: "STRATEGI", ai: "AI GROQ" } as const;

export function SignalStrip({
  card,
  livePrice,
  hero = false,
  children,
}: {
  card: InstrumentCard;
  livePrice: number | null;
  /** Kartu utama: selalu hijau tua & lebih besar (instruksi yang paling penting di layar) */
  hero?: boolean;
  /** Isi tambahan di bawah instruksi (mis. analisis chart pada kartu STRATEGI) */
  children?: React.ReactNode;
}) {
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
          Entry {formatPrice(signal.entry, digits)} ·{" "}
          {signal.trailing_stop != null ? (
            <span className="font-bold text-sell">geser SL ke {formatPrice(signal.trailing_stop, digits)}</span>
          ) : (
            <span className="text-sell">SL {formatPrice(signal.stop_loss, digits)}</span>
          )}{" "}
          ·{" "}
          {signal.take_profit_active ? (
            <span className="text-buy">TP {formatPrice(signal.take_profit, digits)}</span>
          ) : (
            <span className="text-buy">tanpa TP (trailing stop)</span>
          )}
          {signal.suggested_lot ? ` · ${signal.suggested_lot.toFixed(2)} lot` : ""}
          {signal.entry_valid_until && ` · berlaku s/d ${timeWIB(signal.entry_valid_until)}`}
        </span>
      );
    } else {
      headline = `${card.action} kedaluwarsa — jangan masuk`;
      detail =
        signal.trailing_stop != null
          ? `Bila sudah masuk: geser SL ke ${formatPrice(signal.trailing_stop, digits)} (untung dikunci), tunggu CLOSE.`
          : signal.take_profit_active
            ? "Bila sudah terlanjur masuk: biarkan SL/TP bekerja, tunggu CLOSE."
            : "Bila sudah terlanjur masuk: pasang SL saja (tanpa TP); SL akan digeser untuk mengunci untung.";
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
      data-theme={hero ? "dark" : undefined}
      className={`surface relative overflow-hidden rounded-2xl ${
        hero ? "hero py-5 pl-5 pr-4 text-fg" : "py-3 pl-4 pr-3"
      } ${card.is_new_event && card.action !== "WAIT" ? `animate-pulse ring-2 ring-offset-2 ring-offset-bg ${style.ring}` : ""}`}
    >
      {/* aksen warna aksi: garis kiri + gradasi */}
      <span className={`absolute inset-y-0 left-0 w-1.5 ${style.bar}`} />
      <span className={`pointer-events-none absolute inset-0 bg-gradient-to-r ${style.grad} to-transparent`} />
      {hero && (
        <span className="pointer-events-none absolute -bottom-16 -right-10 h-40 w-40 rounded-full bg-accent/20 blur-2xl" />
      )}
      <div className="relative flex items-center gap-3">
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
          <div className={`font-bold leading-tight ${hero ? "text-lg" : ""}`}>{headline}</div>
          {detail && <div className="mt-0.5 line-clamp-2 text-xs leading-snug text-fg-soft">{detail}</div>}
        </div>
      </div>
      {children && <div className="relative mt-3 border-t border-white/10 pt-3">{children}</div>}
    </div>
  );
}
