const TZ = "Asia/Jakarta";

type DateInput = string | number | Date;

/** number = Unix detik (format Lightweight Charts / API candle) */
function toDate(value: DateInput): Date {
  if (value instanceof Date) return value;
  return typeof value === "number" ? new Date(value * 1000) : new Date(value);
}

function parts(value: DateInput, options: Intl.DateTimeFormatOptions) {
  const out: Record<string, string> = {};
  for (const p of new Intl.DateTimeFormat("id-ID", { timeZone: TZ, ...options }).formatToParts(
    toDate(value),
  )) {
    out[p.type] = p.value;
  }
  return out;
}

/** "09:15" — memakai titik dua seperti aplikasi broker */
export function timeWIB(value: DateInput): string {
  const p = parts(value, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return `${p.hour}:${p.minute}`;
}

/** "Rab, 29 Okt 09:15" */
export function dateTimeWIB(value: DateInput): string {
  const p = parts(value, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  return `${p.weekday}, ${p.day} ${p.month} ${p.hour}:${p.minute}`;
}

export function dayMonthWIB(value: DateInput): string {
  const p = parts(value, { day: "numeric", month: "short" });
  return `${p.day} ${p.month}`;
}

export function monthWIB(value: DateInput): string {
  return parts(value, { month: "short" }).month;
}

export function yearWIB(value: DateInput): string {
  return parts(value, { year: "numeric" }).year;
}

export function formatPrice(value: number | null | undefined, digits: number): string {
  return value == null ? "—" : value.toFixed(digits);
}

export function formatPips(value: number | null | undefined, signed = false): string {
  if (value == null) return "—";
  const text = Math.abs(value).toFixed(1);
  if (!signed) return text;
  return value > 0 ? `+${text}` : value < 0 ? `−${text}` : text;
}

export function formatUSD(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

export function relativeTime(value: DateInput, nowMs = Date.now()): string {
  const seconds = Math.round((nowMs - toDate(value).getTime()) / 1000);
  if (seconds < 60) return "baru saja";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} menit lalu`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} jam lalu`;
  return `${Math.round(hours / 24)} hari lalu`;
}

export function countdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
