import { timeWIB } from "./format";
import { TF_SECONDS, type PatternOut, type PatternsResponse, type Timeframe } from "./types";

const TF_MINUTES: Record<Timeframe, number> = { M1: 1, M5: 5, M15: 15, H1: 60, H4: 240 };

/** "4 candle" → durasi nyata sesuai timeframe, mis. M15 → 1 jam, H4 → 16 jam. */
export function horizonText(tf: Timeframe, candles: number): string {
  const minutes = TF_MINUTES[tf] * candles;
  return minutes < 60 ? `${minutes} menit` : `${minutes / 60} jam`;
}

export interface PatternHint {
  pattern: PatternOut;
  timeframe: Timeframe;
  /** waktu buka candle tempat pola muncul (detik), untuk penanda di grafik */
  candleTime: number | null;
  /** peluang harga NAIK setelah pola (null = belum cukup data) */
  up: number | null;
  horizon: string;
}

/**
 * Pola paling berpotensi di candle terakhir: yang peluang historisnya paling jauh dari 50%
 * (lolos uji statistik diutamakan); tanpa data peluang, pola dengan kekuatan tertinggi.
 * Pola di timeframe grafik diutamakan bila potensinya setara.
 */
export function bestPattern(data: PatternsResponse | null, chartTf: Timeframe | null): PatternHint | null {
  if (!data) return null;
  let best: { hint: PatternHint; score: number } | null = null;
  for (const f of data.timeframes) {
    for (const p of f.patterns) {
      if (!p.bias) continue;
      const edge = p.probability != null ? Math.abs(p.probability - 0.5) : -1 + p.strength * 0.01;
      const score = edge + (p.reliable ? 1 : 0) + (f.timeframe === chartTf ? 0.001 : 0);
      if (best && best.score >= score) continue;
      best = {
        score,
        hint: {
          pattern: p,
          timeframe: f.timeframe,
          candleTime: f.candle_time,
          up: p.probability == null ? null : p.bias > 0 ? p.probability : 1 - p.probability,
          horizon: horizonText(f.timeframe, data.horizon),
        },
      };
    }
  }
  return best?.hint ?? null;
}

export interface AnalysisWindow {
  timeframe: Timeframe;
  /** Unix detik: candle timeframe grafik yang sedang berjalan */
  start: number;
  end: number;
  /** "14:30 → 14:45 WIB" */
  label: string;
}

/**
 * Periode yang dinilai analisis: candle timeframe grafik yang sedang berjalan, dari
 * candle sebelumnya tutup sampai candle ini tutup (M15 → 15 menit, H4 → 4 jam).
 */
export function analysisWindow(tf: Timeframe, nowMs = Date.now()): AnalysisWindow {
  const period = TF_SECONDS[tf];
  const now = Math.floor(nowMs / 1000);
  const start = now - (now % period);
  const end = start + period;
  return { timeframe: tf, start, end, label: `${timeWIB(start)} → ${timeWIB(end)} WIB` };
}
