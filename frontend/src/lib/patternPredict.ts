import { TF_SECONDS, type Candle, type PatternMark, type Timeframe } from "./types";

/** Sama dengan MIN_EDGE backend: arah pola baru dipakai bila terbukti benar ≥ 55%. */
export const PREDICT_MIN_CHANCE = 0.55;

export interface Prediction {
  /** waktu buka candle tempat pola muncul (detik) */
  patternTime: number;
  /** waktu buka candle yang diprediksi = waktu masuk (BUY/SELL) */
  time: number;
  /** waktu CLOSE = tutup candle ke-hold setelah masuk (rata-rata untung terbesar di histori) */
  closeAt: number;
  /** lama tahan dalam candle */
  hold: number;
  /** rata-rata hasil bersih historis bila CLOSE di closeAt (pip) */
  avgPips: number | null;
  dir: 1 | -1;
  name: string;
  /** peluang historis pola ini benar (searah teori) */
  chance: number;
  samples: number;
  /** live = candle prediksi sedang berjalan (bisa diikuti sekarang); done = sudah ada hasil */
  status: "live" | "done";
  hit?: boolean;
  /** hasil bersih setelah spread (pip) */
  pips?: number;
}

export interface PredictionSummary {
  list: Prediction[];
  live: Prediction | null;
  done: number;
  hits: number;
  pips: number;
}

/**
 * Prediksi candle berikutnya dari pola candlestick yang TERBUKTI di histori instrumen &
 * timeframe ini (arah sesuai teori benar ≥ 55% dan lolos uji statistik). Masuk di awal candle
 * setelah pola, CLOSE di akhir candle ke-N, N = lama tahan (1…8 candle) yang rata-rata
 * untungnya terbesar di histori (1 bila tidak ada). Hasil = close candle ke-N − close candle
 * pola, dikurangi spread.
 */
export function predictFromPatterns(
  patterns: PatternMark[] | null | undefined,
  candles: Candle[],
  tf: Timeframe,
  pipSize: number,
  spreadPips: number,
): PredictionSummary {
  const period = TF_SECONDS[tf];
  const index = new Map(candles.map((c, i) => [c.time, i]));
  const lastTime = candles.at(-1)?.time ?? 0;
  const list: Prediction[] = [];
  for (const p of patterns ?? []) {
    if (!p.bias || p.probability == null || !p.reliable || p.probability < PREDICT_MIN_CHANCE) continue;
    const i = index.get(p.time);
    if (i == null) continue;
    const dir = p.bias > 0 ? 1 : -1;
    const hold = p.best_hold ?? 1;
    const base = {
      patternTime: p.time,
      dir,
      name: p.name,
      chance: p.probability,
      samples: p.samples,
      hold,
      avgPips: p.best_pips ?? null,
    } as const;
    const next = candles[i + 1];
    if (!next) {
      // Candle pola = candle terakhir; candle prediksi belum muncul di data → sedang berjalan
      if (p.time === lastTime)
        list.push({
          ...base,
          time: p.time + period,
          closeAt: p.time + (1 + hold) * period,
          status: "live",
        });
      continue;
    }
    // Candle CLOSE (ke-hold) belum ada / masih berjalan → posisi masih terbuka
    const exit = candles[i + hold];
    const exitOpen = !exit || (i + hold === candles.length - 1 && exit.time + period > Date.now() / 1000);
    if (exitOpen) {
      list.push({
        ...base,
        time: next.time,
        closeAt: next.time + hold * period,
        status: "live",
      });
      continue;
    }
    const move = (exit.close - candles[i].close) * dir;
    const pips = move / pipSize - spreadPips;
    list.push({
      ...base,
      time: next.time,
      closeAt: exit.time + period,
      status: "done",
      hit: pips > 0,
      pips,
    });
  }
  const done = list.filter((p) => p.status === "done");
  return {
    list,
    live: list.find((p) => p.status === "live") ?? null,
    done: done.length,
    hits: done.filter((p) => p.hit).length,
    pips: done.reduce((sum, p) => sum + (p.pips ?? 0), 0),
  };
}
