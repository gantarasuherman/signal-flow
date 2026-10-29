"use client";

import Link from "next/link";
import { dateTimeWIB, formatPips, formatPrice, formatUSD, relativeTime, timeWIB } from "@/lib/format";
import { ACTION_HINT, ACTION_STYLE, STATUS_STYLE, liveEntryState } from "@/lib/signal";
import type { InstrumentCard, SignalView } from "@/lib/types";

interface Props {
  card: InstrumentCard;
  /** harga live (sudah disesuaikan offset) bila grafik instrumen ini sedang dibuka */
  livePrice?: number | null;
  href?: string;
}

function PriceRow({
  label,
  price,
  pips,
  digits,
  tone,
}: {
  label: string;
  price: number | null;
  pips?: string;
  digits: number;
  tone: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-1.5">
      <span className="text-sm text-muted">{label}</span>
      <span className="tabular flex items-baseline gap-2">
        <span className={`text-2xl font-bold ${tone}`}>{formatPrice(price, digits)}</span>
        {pips && <span className="w-24 text-right text-sm text-muted">{pips}</span>}
      </span>
    </div>
  );
}

function EntryBanner({ signal, livePrice }: { signal: SignalView; livePrice?: number | null }) {
  const { state, distance } = liveEntryState(signal, livePrice ?? signal.current_price);
  if (state === "CLOSED") return null;
  const distanceText =
    distance != null ? `${formatPips(distance, true)} pip dari entry (batas ${signal.validity_pips} pip)` : "";
  if (state === "VALID") {
    return (
      <div className="rounded-lg border border-buy/30 bg-buy/10 px-3 py-2 text-sm text-ok">
        <strong>✓ Masih bisa masuk</strong>
        {signal.entry_valid_until && <> sampai {timeWIB(signal.entry_valid_until)} WIB</>}
        {distanceText && <div className="text-xs opacity-80">Harga kini {distanceText}</div>}
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-close/40 bg-close/10 px-3 py-2 text-sm text-warn">
      <strong>⚠ Kedaluwarsa, jangan masuk</strong>
      <div className="text-xs opacity-80">
        {state === "EXPIRED_TIME"
          ? `Sinyal sudah lewat batas waktu masuk (${signal.entry_valid_until ? timeWIB(signal.entry_valid_until) : "-"} WIB).`
          : `Harga sudah terlalu jauh: ${distanceText}.`}{" "}
        Sinyal tetap dipantau sampai TP/SL/CLOSE.
      </div>
    </div>
  );
}

function LotBox({ signal }: { signal: SignalView }) {
  if (signal.action === "CLOSE" || (signal.status !== "ACTIVE" && signal.status !== "EXPIRED")) return null;
  if (signal.capital == null) {
    return (
      <Link href="/settings" className="block rounded-lg bg-panel-2 px-3 py-2 text-sm text-muted">
        Isi modal di <span className="text-fg underline">Pengaturan</span> untuk saran ukuran lot.
      </Link>
    );
  }
  return (
    <div className="flex items-baseline justify-between rounded-lg bg-panel-2 px-3 py-2">
      <span className="text-sm text-muted">Lot disarankan</span>
      <span className="text-right">
        <span className="tabular text-2xl font-bold">
          {signal.suggested_lot != null && signal.suggested_lot > 0 ? signal.suggested_lot.toFixed(2) : "—"}
        </span>
        <span className="block text-xs text-muted">
          {signal.suggested_lot === 0
            ? "Modal terlalu kecil untuk jarak SL ini"
            : `risiko ${formatUSD(signal.risk_amount)} (${signal.risk_percent}% dari ${formatUSD(signal.capital)})`}
        </span>
      </span>
    </div>
  );
}

export function SignalCard({ card, livePrice, href }: Props) {
  const { instrument: inst, signal } = card;
  const digits = inst.digits;
  const action = card.action;
  const style = ACTION_STYLE[action];
  const price = livePrice ?? card.current_price;
  const showSignal = signal && (action !== "WAIT" || signal.status === "ACTIVE");
  const isClose = signal?.action === "CLOSE";

  const header = (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="text-lg font-bold tracking-wide">
          {inst.symbol}
          {card.source === "ai" && (
            <span className="ml-2 rounded bg-ai/20 px-1.5 py-0.5 align-middle text-[10px] font-bold text-ai">
              AI GROQ · eksperimen
            </span>
          )}
        </div>
        <div className="truncate text-xs text-muted">{inst.name}</div>
      </div>
      <div className="text-right">
        <div className="tabular text-lg font-semibold">{formatPrice(price, digits)}</div>
        <div className="text-[11px] text-muted">
          {livePrice != null || card.price_source === "live" ? "harga live" : "tutup M15 terakhir"}
          {inst.price_offset !== 0 && " · disesuaikan broker"}
        </div>
      </div>
    </div>
  );

  return (
    <article className="surface relative overflow-hidden rounded-2xl p-4">
      <span className={`absolute inset-x-0 top-0 h-1 ${style.bar}`} />
      <span className={`pointer-events-none absolute inset-0 bg-gradient-to-b ${style.grad} to-transparent opacity-60`} />
      <div className="relative">
      {href ? (
        <Link href={href} className="block">
          {header}
        </Link>
      ) : (
        header
      )}

      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <div className={`flex items-center gap-1 text-5xl font-black leading-none tracking-tight ${style.text}`}>
            <span className="text-2xl">{style.icon}</span>
            {style.label}
          </div>
          <div className="mt-1 text-sm text-muted">
            {isClose && signal?.closes_action ? `Tutup posisi ${signal.closes_action}` : ACTION_HINT[action]}
          </div>
        </div>
        <div className="space-y-1 text-right text-xs text-muted">
          {card.is_new_event && action !== "WAIT" && (
            <span className={`block animate-pulse font-black tracking-wider ${style.text}`}>● BARU</span>
          )}
          {signal && showSignal && (
            <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS_STYLE[signal.status]}`}>
              {signal.status_label}
            </span>
          )}
          {!inst.market_open && <div className="mt-1 text-close">Pasar tutup</div>}
        </div>
      </div>

      {showSignal && signal && (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap gap-x-3 text-xs text-muted">
            <span>
              Sinyal {signal.timeframe} · {dateTimeWIB(signal.signal_time)} WIB
            </span>
            {signal.confidence_label && (
              <span>
                Keyakinan <strong className="uppercase text-fg">{signal.confidence_label}</strong>
              </span>
            )}
          </div>

          {!isClose ? (
            <div className="divide-y divide-line rounded-xl bg-bg/60 px-3">
              <PriceRow label="Entry" price={signal.entry} digits={digits} tone="text-fg" />
              <PriceRow
                label="Stop loss"
                price={signal.stop_loss}
                pips={`${formatPips(signal.sl_pips)} pip`}
                digits={digits}
                tone="text-sell"
              />
              {signal.trailing_stop != null && (
                <PriceRow
                  label="Geser SL ke (trailing)"
                  price={signal.trailing_stop}
                  pips="untung dikunci"
                  digits={digits}
                  tone="text-sell"
                />
              )}
              <PriceRow
                label={signal.take_profit_active ? "Take profit" : "Target awal (TP dilepas)"}
                price={signal.take_profit}
                pips={
                  signal.take_profit_active
                    ? `${formatPips(signal.tp_pips)} pip`
                    : "jangan pasang TP; trailing stop yang menutup"
                }
                digits={digits}
                tone={signal.take_profit_active ? "text-buy" : "text-muted"}
              />
              <div className="flex justify-between py-1.5 text-xs text-muted">
                <span>R:R 1:{signal.risk_reward?.toFixed(1) ?? "—"}</span>
                <span>Spread ±{signal.spread_pips ?? inst.spread_pips} pip</span>
              </div>
            </div>
          ) : (
            <div className="rounded-xl bg-bg/60 px-3 py-2">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-muted">Hasil (bila masuk di entry)</span>
                <span
                  className={`tabular text-2xl font-bold ${(signal.result_pips ?? 0) >= 0 ? "text-buy" : "text-sell"}`}
                >
                  {formatPips(signal.result_pips, true)} pip
                </span>
              </div>
              {signal.close_reason && <p className="mt-1 text-sm">{signal.close_reason}</p>}
            </div>
          )}

          {!isClose && <EntryBanner signal={signal} livePrice={livePrice} />}
          <LotBox signal={signal} />

          {signal.status !== "ACTIVE" && signal.status !== "EXPIRED" && !isClose && signal.result_pips != null && (
            <div className="text-sm">
              Hasil:{" "}
              <strong className={signal.result_pips >= 0 ? "text-buy" : "text-sell"}>
                {formatPips(signal.result_pips, true)} pip
              </strong>{" "}
              · {signal.close_reason}
            </div>
          )}

          <p className="text-sm leading-relaxed text-fg-soft">{signal.reason_text}</p>
        </div>
      )}

      {!showSignal && card.analysis && (
        <div className="mt-3 space-y-2">
          <ul className="space-y-1 text-sm text-fg-soft">
            {card.analysis.reasons.map((reason) => (
              <li key={reason}>• {reason}</li>
            ))}
          </ul>
          {card.analysis.filters.map((f) => (
            <div key={f} className="rounded-lg bg-close/10 px-3 py-1.5 text-xs text-warn">
              ⚠ {f}
            </div>
          ))}
          <div className="text-xs text-muted">Dianalisis {relativeTime(card.analysis.analyzed_at)}</div>
        </div>
      )}
      {!showSignal && !card.analysis && (
        <p className="mt-3 text-sm text-muted">Menunggu analisis pertama dari worker…</p>
      )}
      </div>
    </article>
  );
}
