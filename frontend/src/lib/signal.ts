import type { Action, EntryState, SignalView } from "./types";

export const ACTION_STYLE: Record<
  Action,
  { text: string; bg: string; border: string; ring: string; label: string; grad: string; bar: string; icon: string }
> = {
  BUY: { text: "text-buy", bg: "bg-buy/10", border: "border-buy/40", ring: "ring-buy", label: "BUY",
         grad: "from-buy/25 via-buy/5", bar: "bg-buy", icon: "▲" },
  SELL: { text: "text-sell", bg: "bg-sell/10", border: "border-sell/40", ring: "ring-sell", label: "SELL",
          grad: "from-sell/25 via-sell/5", bar: "bg-sell", icon: "▼" },
  CLOSE: { text: "text-close", bg: "bg-close/10", border: "border-close/40", ring: "ring-close", label: "CLOSE",
           grad: "from-close/25 via-close/5", bar: "bg-close", icon: "■" },
  WAIT: { text: "text-wait", bg: "bg-panel", border: "border-line", ring: "ring-line", label: "WAIT",
          grad: "from-wait/10 via-transparent", bar: "bg-wait", icon: "" },
};

export const ACTION_HINT: Record<Action, string> = {
  BUY: "Beli",
  SELL: "Jual",
  CLOSE: "Tutup posisi",
  WAIT: "Tunggu, belum ada setup",
};

export const STATUS_STYLE: Record<SignalView["status"], string> = {
  ACTIVE: "bg-buy/15 text-buy",
  EXPIRED: "bg-close/15 text-close",
  HIT_TP: "bg-buy/15 text-buy",
  HIT_SL: "bg-sell/15 text-sell",
  CLOSED: "bg-wait/20 text-fg-soft",
};

/**
 * Hitung ulang status entry dengan harga live di sisi klien (logika sama dengan backend
 * `entry_state`). Harga entry & live sama-sama sudah disesuaikan offset.
 */
export function liveEntryState(
  signal: SignalView,
  livePrice: number | null,
  nowMs = Date.now(),
): { state: EntryState; distance: number | null } {
  let distance: number | null = signal.distance_from_entry_pips;
  if (livePrice != null && signal.entry != null && signal.action !== "CLOSE") {
    const direction = signal.action === "BUY" ? 1 : -1;
    distance = Math.round(((livePrice - signal.entry) * direction * 10) / signal.pip_size) / 10;
  }
  if (signal.status !== "ACTIVE" && signal.status !== "EXPIRED") return { state: "CLOSED", distance };
  if (signal.entry_valid_until && nowMs > new Date(signal.entry_valid_until).getTime())
    return { state: "EXPIRED_TIME", distance };
  if (distance != null && Math.abs(distance) > signal.validity_pips)
    return { state: "EXPIRED_DISTANCE", distance };
  return { state: "VALID", distance };
}
