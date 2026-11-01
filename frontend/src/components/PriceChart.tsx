"use client";

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  TickMarkType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type LogicalRange,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { endpoints } from "@/lib/api";
import { dateTimeWIB, dayMonthWIB, formatPrice, monthWIB, timeWIB, yearWIB } from "@/lib/format";
import { useRealtime, useRealtimeMessages } from "@/lib/realtime";
import type { AnalysisWindow, PatternHint } from "@/lib/patternHint";
import { predictFromPatterns, type PredictionSummary } from "@/lib/patternPredict";
import { readPalette, useTheme } from "@/lib/theme";
import {
  TF_SECONDS,
  TIMEFRAMES,
  type CandlesResponse,
  type ChartRead,
  type PredictionSummary as ForwardSummary,
  type PatternMark,
  type SignalView,
  type Timeframe,
} from "@/lib/types";

const COLORS = {
  bg: "#0b0e11",
  grid: "#151a21",
  line: "#262f3a",
  text: "#8b95a1",
  up: "#16c784",
  down: "#ea3943",
  close: "#f5a524",
  ema20: "#f0b90b",
  ema50: "#3b82f6",
  ema200: "#c084fc",
  bb: "#64748b",
  macd: "#3b82f6",
  signal: "#f59e0b",
  ai: "#a78bfa",
};

/** Awalan label untuk sinyal AI di grafik. */
const tag = (s: SignalView) => (s.source === "ai" ? "AI " : "");

type Toggles = {
  ema: boolean;
  bb: boolean;
  rsi: boolean;
  macd: boolean;
  pola: boolean;
  /** titik BUY/SELL/CLOSE dari ANALISIS CHART */
  analisis: boolean;
};
const DEFAULT_TOGGLES: Toggles = {
  ema: true,
  bb: false,
  rsi: true,
  macd: false,
  pola: true,
  analisis: true,
};
const STORAGE_KEY = "signalflow:chart";

function loadPrefs(): { tf: Timeframe; toggles: Toggles } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as {
        tf?: Timeframe;
        toggles?: Partial<Toggles>;
      };
      return {
        tf: parsed.tf && TIMEFRAMES.includes(parsed.tf) ? parsed.tf : "M15",
        toggles: { ...DEFAULT_TOGGLES, ...parsed.toggles },
      };
    }
  } catch {
    // localStorage tidak tersedia (mode privat) — pakai bawaan
  }
  return { tf: "M15", toggles: DEFAULT_TOGGLES };
}

const ts = (t: number) => t as UTCTimestamp;

function tickMark(time: Time, type: TickMarkType): string {
  const t = time as number;
  switch (type) {
    case TickMarkType.Year:
      return yearWIB(t);
    case TickMarkType.Month:
      return monthWIB(t);
    case TickMarkType.DayOfMonth:
      return dayMonthWIB(t);
    default:
      return timeWIB(t);
  }
}

/** Bar (pada timeframe grafik) tempat sinyal muncul: bar yang berisi detik sebelum candle M15 tutup. */
function markerTime(signalTimeIso: string, tf: Timeframe): number {
  const t = Math.floor(new Date(signalTimeIso).getTime() / 1000) - 1;
  return t - (t % TF_SECONDS[tf]);
}

/** Hasil pip singkat untuk label penanda, mis. "+45" / "−20". */
const pipsText = (p: number | null) =>
  p == null ? "" : ` ${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(Math.round(p))} pip`;

/**
 * Titik kapan harus BUY / SELL (candle entry, dengan harga) dan kapan posisi selesai:
 * TP tercapai, SL tersentuh, atau CLOSE (dengan hasil pip). Sinyal CLOSE tercatat sebagai
 * baris sendiri yang menunjuk posisi induknya (parent_id).
 */
function buildMarkers(
  signals: SignalView[],
  tf: Timeframe,
  first: number,
  last: number,
  digits: number,
  colors: { up: string; down: string; close: string } = COLORS,
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  const inRange = (t: number) => t >= first && t <= last;
  const byId = new Map(signals.map((s) => [s.id, s]));
  const closedByRow = new Set(
    signals.filter((s) => s.action === "CLOSE" && s.parent_id != null).map((s) => s.parent_id),
  );

  for (const s of signals) {
    const time = markerTime(s.signal_time, tf);
    if (s.action === "BUY" || s.action === "SELL") {
      const buy = s.action === "BUY";
      if (inRange(time))
        markers.push({
          time: ts(time),
          position: buy ? "belowBar" : "aboveBar",
          shape: buy ? "arrowUp" : "arrowDown",
          color: buy ? colors.up : colors.down,
          text: `${tag(s)}${s.action}${s.entry != null ? ` ${s.entry.toFixed(digits)}` : ""}`,
        });
      // Akhir posisi tanpa baris CLOSE tersendiri: TP / SL / batas waktu
      if (s.closed_at && !closedByRow.has(s.id)) {
        const exit = markerTime(s.closed_at, tf);
        if (!inRange(exit)) continue;
        const label = s.status === "HIT_TP" ? "TP ✓" : s.status === "HIT_SL" ? "SL ✗" : "Tutup";
        const good = (s.result_pips ?? 0) > 0;
        markers.push({
          time: ts(exit),
          position: buy ? "aboveBar" : "belowBar",
          shape: "circle",
          color:
            s.status === "HIT_TP" || (s.status === "CLOSED" && good)
              ? colors.up
              : s.status === "HIT_SL"
                ? colors.down
                : colors.close,
          text: `${tag(s)}${label}${pipsText(s.result_pips)}`,
        });
      }
    } else if (inRange(time)) {
      const parent = s.parent_id != null ? byId.get(s.parent_id) : undefined;
      const result = parent?.result_pips ?? s.result_pips;
      markers.push({
        time: ts(time),
        position: s.closes_action === "SELL" ? "belowBar" : "aboveBar",
        shape: "square",
        color: colors.close,
        text: `${tag(s)}CLOSE${pipsText(result)}`,
      });
    }
  }
  return markers.sort((a, b) => (a.time as number) - (b.time as number));
}

/** Penanda pola candlestick KUAT saja (di area support/resistance dan searah tren), agar grafik tidak penuh. */
/** Layar sempit (HP): nama pola tidak ditulis di grafik agar tidak menumpuk di atas candle. */
const MARKER_TEXT_MIN_WIDTH = 640;

function patternMarkers(
  patterns: PatternMark[],
  colors: { up: string; down: string },
  withText: boolean,
): SeriesMarker<Time>[] {
  return patterns
    .filter((p) => p.strength >= 3)
    .map((p) => ({
      time: ts(p.time),
      position: p.bias > 0 ? "belowBar" : "aboveBar",
      shape: "circle",
      size: 0.6,
      color: `${p.bias > 0 ? colors.up : colors.down}99`,
      text: withText ? `${p.name} ★` : "",
    }));
}

/** Keterangan di grafik: pola paling berpotensi dan peluang harga naik/turun setelahnya. */
const LEAN = {
  naik: { icon: "▲", text: "text-buy", dir: 1 },
  turun: { icon: "▼", text: "text-sell", dir: -1 },
  netral: { icon: "■", text: "text-fg-soft", dir: 0 },
} as const;

/** Peluang di bawah ini dianggap seperti lempar koin (sama dengan MIN_EDGE backend). */
const COIN_FLIP_EDGE = 0.55;

/**
 * Ringkasan di grafik = analisis chart yang SAMA dengan kartu STRATEGI, lalu pola candle
 * sebagai pendukung beserta kecocokannya dengan analisis (searah / melawan / lempar koin).
 * Ringkas satu-dua baris agar tidak menutupi titik BUY/SELL/CLOSE; ketuk untuk rincian.
 */
function ChartSummary({
  read,
  hint,
  window,
  pred,
  forward,
}: {
  read: ChartRead | null;
  hint: PatternHint | null;
  window: AnalysisWindow | null;
  pred: PredictionSummary | null;
  forward: ForwardSummary | null;
}) {
  const [open, setOpen] = useState(false);
  if (!read && !hint && !pred) return null;
  const lean = read ? LEAN[read.lean] : null;
  const upPct = hint?.up != null ? Math.round(hint.up * 100) : null;
  const patternDir = upPct == null ? 0 : upPct >= 50 ? 1 : -1;
  const edge = upPct == null ? 0 : Math.max(upPct, 100 - upPct) / 100;
  let fit: { label: string; className: string } | null = null;
  if (hint) {
    if (upPct == null) fit = { label: "belum teruji", className: "text-muted" };
    else if (edge < COIN_FLIP_EDGE) fit = { label: "≈ lempar koin", className: "text-muted" };
    else if (!lean || lean.dir === 0) fit = { label: "analisis netral", className: "text-muted" };
    else if (patternDir === lean.dir) fit = { label: "✓ searah analisis", className: "text-buy" };
    else fit = { label: "⚠ melawan analisis", className: "text-warn" };
  }
  return (
    <button
      type="button"
      onClick={() => setOpen((o) => !o)}
      aria-expanded={open}
      className="pointer-events-auto block max-w-[280px] space-y-0.5 rounded-lg bg-bg/75 px-2 py-1 text-left text-[10px] leading-tight text-fg-soft shadow-sm backdrop-blur-sm"
    >
      {read && lean && (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <span className="text-muted">Analisis {read.timeframe}</span>
          <b className={`text-[11px] ${lean.text}`}>
            {lean.icon} {read.lean.toUpperCase()}
            {read.lean !== "netral" && ` · ${read.strength}`}
          </b>
          <span className="text-muted">{open ? "▴" : "▾"}</span>
        </span>
      )}
      {read && (() => {
        const closes = read.events.filter((e) => e.action === "CLOSE").map((e) => e.result_pips ?? 0);
        if (!closes.length) return null;
        const wins = closes.filter((p) => p > 0).length;
        const net = closes.reduce((a, b) => a + b, 0);
        return (
          <span className="tabular block whitespace-nowrap">
            📊 Titik analisis: {closes.length} siklus · benar {wins} ({Math.round((wins / closes.length) * 100)}%) ·{" "}
            <b className={net >= 0 ? "text-buy" : "text-sell"}>
              {net >= 0 ? "+" : "−"}
              {Math.abs(Math.round(net))} pip
            </b>
          </span>
        );
      })()}
      {window && read && window.timeframe === read.timeframe && (
        <span className="tabular block whitespace-nowrap font-semibold">⏱ {window.label}</span>
      )}
      {hint && (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <span>🕯️</span>
          <b className="text-fg">{hint.pattern.name}</b>
          <span className="rounded bg-panel-2 px-1 font-bold">{hint.timeframe}</span>
          {upPct != null && (
            <span className="tabular">
              ▲{upPct}% ▼{100 - upPct}%
            </span>
          )}
          {fit && <span className={`font-semibold ${fit.className}`}>{fit.label}</span>}
        </span>
      )}
      {pred?.live && (
        <span className={`block whitespace-nowrap font-bold ${pred.live.dir > 0 ? "text-buy" : "text-sell"}`}>
          ▶ {pred.live.dir > 0 ? "BUY" : "SELL"} {timeWIB(pred.live.time)} · CLOSE {timeWIB(pred.live.closeAt)} WIB
          <span className="font-normal text-muted">
            {" "}
            ({pred.live.name}, benar {Math.round(pred.live.chance * 100)}%
            {pred.live.avgPips != null && `, rata-rata +${pred.live.avgPips.toFixed(1)} pip`})
          </span>
        </span>
      )}
      {pred && (
        <span className="tabular block whitespace-nowrap">
          🎯{" "}
          {pred.list.length === 0
            ? "Belum ada pola terbukti di grafik ini"
            : `Prediksi di grafik: ${pred.done}× · benar ${pred.hits}${pred.done ? ` (${Math.round((pred.hits / pred.done) * 100)}%)` : ""} · ${pred.pips >= 0 ? "+" : "−"}${Math.abs(Math.round(pred.pips))} pip`}
        </span>
      )}
      {pred && forward && (
        <span className="tabular block whitespace-nowrap text-muted">
          📒 Uji maju:{" "}
          {forward.done === 0
            ? forward.pending
              ? `${forward.pending} menunggu hasil`
              : "belum ada prediksi tercatat"
            : `${forward.done}× · benar ${Math.round((forward.hits / forward.done) * 100)}% · ${forward.pips >= 0 ? "+" : "−"}${Math.abs(Math.round(forward.pips))} pip`}
        </span>
      )}
      {open && (
        <span className="block space-y-1 pt-0.5 whitespace-normal">
          {pred && (
            <span className="block text-muted">
              📒 Uji maju = prediksi yang dicatat SAAT muncul (sebelum hasilnya diketahui). Ini ukuran yang jujur; rekap
              🎯 di atas dihitung ulang dari histori sehingga cenderung terlalu optimis. Lihat Riwayat → Prediksi pola.
            </span>
          )}
          {pred && (
            <span className="block text-muted">
              🎯 Prediksi = candle setelah pola yang terbukti benar ≥55% di histori: masuk di awal candle, CLOSE di
              akhir candle. ✓/✗ = hasil sebenarnya setelah spread. Pola lain tidak diberi prediksi.
            </span>
          )}
          {read && <span className="block">{read.watch}</span>}
          {read && read.events.length > 0 && (
            <span className="block text-muted">
              📊 Titik analisis = BUY saat analisis berubah jadi NAIK, SELL saat jadi TURUN, CLOSE saat arahnya hilang
              atau berbalik. Harga = tutup candle itu; ✓/✗ = hasil setelah spread. Bukan sinyal strategi teruji.
            </span>
          )}
          {hint && (
            <span className="block text-muted">
              Pola: {hint.pattern.meaning}.{" "}
              {upPct != null
                ? `Historis: dalam ${hint.horizon} setelah pola ini, harga naik ${upPct} dari 100 kali (${hint.pattern.samples} kejadian).`
                : "Kejadian historis belum cukup untuk dinilai."}{" "}
              Arah utama mengikuti analisis; pola hanya pendukung.
            </span>
          )}
        </span>
      )}
    </button>
  );
}

interface Props {
  symbol: string;
  digits: number;
  /** sinyal aktif (strategi dan/atau AI) → garis Entry/SL/TP */
  signals: SignalView[];
  /** riwayat sinyal instrumen ini, untuk penanda panah */
  history: SignalView[];
  /** naik setiap kali ada analisis baru → muat ulang candle tertutup */
  reloadKey: number;
  onLivePrice?: (price: number | null) => void;
  /** timeframe grafik berubah (mis. panel pola ikut membaca timeframe ini) */
  onTimeframe?: (tf: Timeframe) => void;
  /** pola paling berpotensi + peluang naik/turun → keterangan & penanda di grafik */
  patternHint?: PatternHint | null;
  /** analisis chart yang sama dengan kartu STRATEGI → ringkasan + garis support/resistance */
  chartRead?: ChartRead | null;
  /** periode yang dinilai analisis (candle timeframe grafik yang berjalan) */
  analysisWindow?: AnalysisWindow | null;
  /** untuk hasil prediksi pola dalam pip bersih */
  pipSize?: number;
  spreadPips?: number;
  /** rekap uji maju prediksi pola (instrumen & timeframe ini) */
  forward?: ForwardSummary | null;
}

export default function PriceChart({
  symbol,
  digits,
  signals,
  history,
  reloadKey,
  onLivePrice,
  onTimeframe,
  patternHint = null,
  chartRead = null,
  analysisWindow = null,
  pipSize = 0.0001,
  spreadPips = 0,
  forward = null,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lastBarTime = useRef(0);
  const savedRange = useRef<{ key: string; range: LogicalRange | null } | null>(null);
  const [prefs, setPrefs] = useState<{
    tf: Timeframe;
    toggles: Toggles;
  } | null>(null);
  const [data, setData] = useState<CandlesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [legend, setLegend] = useState<{
    o: number;
    h: number;
    l: number;
    c: number;
    time: number;
  } | null>(null);
  const [streaming, setStreaming] = useState(false);
  const hovering = useRef(false);
  // Layar penuh: grafik menutupi seluruh layar (overlay CSS, jalan juga di iPhone yang tidak
  // mendukung Fullscreen API), plus Fullscreen API bila browser mendukung agar bilah browser hilang
  const [full, setFull] = useState(false);
  useEffect(() => {
    if (!full) return;
    const doc = document.documentElement;
    if (!document.fullscreenElement) doc.requestFullscreen?.().catch(() => undefined);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setFull(false);
    // Keluar lewat tombol/gesture browser → tutup overlay juga
    const onChange = () => !document.fullscreenElement && setFull(false);
    window.addEventListener("keydown", onKey);
    document.addEventListener("fullscreenchange", onChange);
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("fullscreenchange", onChange);
      if (document.fullscreenElement) document.exitFullscreen?.().catch(() => undefined);
    };
  }, [full]);
  const { send } = useRealtime();
  const { resolved } = useTheme();

  useEffect(() => setPrefs(loadPrefs()), []);
  useEffect(() => {
    if (prefs) onTimeframe?.(prefs.tf);
  }, [prefs?.tf, onTimeframe]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!prefs) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
      // abaikan
    }
  }, [prefs]);

  const tf = prefs?.tf;

  // Prediksi candle berikutnya dari pola terbukti (timeframe grafik), dari data yang sama
  const prediction = useMemo(() => {
    if (!data || !tf || data.timeframe !== tf) return null;
    const bars = [...data.candles];
    if (data.live && (!bars.length || data.live.time >= bars.at(-1)!.time)) {
      if (bars.length && data.live.time === bars.at(-1)!.time) bars.pop();
      bars.push(data.live);
    }
    return predictFromPatterns(data.patterns, bars, tf, pipSize, spreadPips);
  }, [data, tf, pipSize, spreadPips]);

  // Muat candle tertutup + indikator
  useEffect(() => {
    if (!tf) return;
    let active = true;
    endpoints
      .candles(symbol, tf)
      .then((res) => {
        if (!active) return;
        setData(res);
        setError(null);
      })
      .catch((e: Error) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [symbol, tf, reloadKey]);

  // Berlangganan live candle lewat WebSocket
  useEffect(() => {
    if (!tf) return;
    setStreaming(false);
    send({ action: "subscribe_live", symbol, timeframe: tf });
    return () => send({ action: "unsubscribe_live" });
  }, [symbol, tf, send]);

  useRealtimeMessages(
    useCallback(
      (msg) => {
        if (msg.type !== "live" || msg.symbol !== symbol || msg.timeframe !== tf || !msg.candle) return;
        setStreaming(Boolean(msg.streaming));
        const series = candleSeries.current;
        if (!series || msg.candle.time < lastBarTime.current) return;
        series.update({ ...msg.candle, time: ts(msg.candle.time) });
        lastBarTime.current = msg.candle.time;
        onLivePrice?.(msg.candle.close);
        if (!hovering.current) {
          const c = msg.candle;
          setLegend({
            o: c.open,
            h: c.high,
            l: c.low,
            c: c.close,
            time: c.time,
          });
        }
      },
      [symbol, tf, onLivePrice],
    ),
  );

  // Bangun ulang grafik bila data / pilihan indikator berubah
  useEffect(() => {
    const el = container.current;
    if (!el || !data || !prefs || data.timeframe !== prefs.tf) return;
    const { toggles } = prefs;
    const rangeKey = `${symbol}:${prefs.tf}`;

    // Warna mengikuti tema (variabel CSS); grafik dibangun ulang saat tema berganti
    const C = { ...COLORS, ...readPalette() };
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: C.panel || C.bg }, // grafik di atas kartu
        textColor: C.text,
        fontSize: 11,
        panes: { separatorColor: C.line, separatorHoverColor: C.line },
      },
      grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
      rightPriceScale: { borderColor: C.line },
      timeScale: {
        borderColor: C.line,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        tickMarkFormatter: tickMark,
      },
      localization: {
        locale: "id-ID",
        timeFormatter: (t: Time) => `${dateTimeWIB(t as number)} WIB`,
        priceFormatter: (p: number) => p.toFixed(digits),
      },
      crosshair: { mode: CrosshairMode.Normal },
      // Geser vertikal di atas grafik tetap menggulir halaman; pinch & geser horizontal untuk grafik
      handleScroll: { vertTouchDrag: false },
    });
    chartRef.current = chart;

    const candles = data.candles.map((c) => ({ ...c, time: ts(c.time) }));
    if (data.live && (!candles.length || data.live.time >= (candles.at(-1)!.time as number))) {
      if (candles.length && data.live.time === (candles.at(-1)!.time as number)) candles.pop();
      candles.push({ ...data.live, time: ts(data.live.time) });
    }
    const series = chart.addSeries(CandlestickSeries, {
      upColor: C.up,
      downColor: C.down,
      borderVisible: false,
      wickUpColor: C.up,
      wickDownColor: C.down,
      priceFormat: { type: "price", precision: digits, minMove: 10 ** -digits },
    });
    series.setData(candles);
    candleSeries.current = series;
    lastBarTime.current = (candles.at(-1)?.time as number | undefined) ?? 0;
    if (data.live) onLivePrice?.(data.live.close);

    const ind = data.indicators ?? {};
    const line = (key: string, color: string, pane = 0, extra: object = {}) => {
      const points = ind[key];
      if (!points?.length) return null;
      const s = chart.addSeries(
        LineSeries,
        {
          color,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          ...extra,
        },
        pane,
      );
      s.setData(points.map((p) => ({ time: ts(p.time), value: p.value })));
      return s;
    };

    if (toggles.ema) {
      line("ema20", C.ema20);
      line("ema50", C.ema50);
      line("ema200", C.ema200, 0, { lineWidth: 2 });
    }
    if (toggles.bb) {
      line("bb_upper", C.bb);
      line("bb_mid", C.bb, 0, { lineStyle: LineStyle.Dotted });
      line("bb_lower", C.bb);
    }

    let pane = 1;
    if (toggles.rsi && ind.rsi?.length) {
      const rsi = line("rsi", "#a78bfa", pane, {
        lastValueVisible: true,
        priceFormat: { type: "price", precision: 1, minMove: 0.1 },
      });
      rsi?.createPriceLine({
        price: 70,
        color: C.line,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: false,
        title: "",
      });
      rsi?.createPriceLine({
        price: 30,
        color: C.line,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: false,
        title: "",
      });
      pane += 1;
    }
    if (toggles.macd && ind.macd_hist?.length) {
      const hist = chart.addSeries(
        HistogramSeries,
        {
          priceLineVisible: false,
          lastValueVisible: false,
          priceFormat: {
            type: "price",
            precision: digits + 1,
            minMove: 10 ** -(digits + 1),
          },
        },
        pane,
      );
      hist.setData(
        ind.macd_hist.map((p) => ({
          time: ts(p.time),
          value: p.value,
          color: p.value >= 0 ? `${C.up}99` : `${C.down}99`,
        })),
      );
      line("macd", C.macd, pane);
      line("macd_signal", C.signal, pane);
    }
    const panes = chart.panes();
    panes[0]?.setStretchFactor(3);
    for (const p of panes.slice(1)) p.setStretchFactor(1);

    // Penanda sinyal & garis entry/SL/TP
    if (candles.length) {
      const first = candles[0].time as number;
      const last = candles.at(-1)!.time as number;
      const marks = buildMarkers(history, prefs.tf, first, last, digits, C);
      if (toggles.pola && data.patterns)
        marks.push(...patternMarkers(data.patterns, C, el.clientWidth >= MARKER_TEXT_MIN_WIDTH));
      // Prediksi: BUY/SELL di candle setelah pola terbukti, CLOSE di akhir candle itu
      if (toggles.pola && prediction) {
        for (const p of prediction.list) {
          if (p.time < first || p.time > last) continue;
          const side = p.dir > 0 ? "BUY" : "SELL";
          const result =
            p.status === "live"
              ? `▶ ${side} → CLOSE ${timeWIB(p.closeAt)}`
              : `${side} ${p.hit ? "✓" : "✗"}${(p.pips ?? 0) >= 0 ? "+" : "−"}${Math.abs(Math.round(p.pips ?? 0))}`;
          marks.push({
            time: ts(p.time),
            position: p.dir > 0 ? "belowBar" : "aboveBar",
            shape: p.dir > 0 ? "arrowUp" : "arrowDown",
            color: p.status === "live" ? (p.dir > 0 ? C.up : C.down) : p.hit ? `${C.up}cc` : `${C.down}cc`,
            text: result,
          });
          // CLOSE terbaik lebih dari 1 candle: tandai candle tempat posisi ditutup
          const exitAt = p.closeAt - TF_SECONDS[prefs.tf];
          if (p.hold > 1 && exitAt <= last) {
            marks.push({
              time: ts(exitAt),
              position: p.dir > 0 ? "aboveBar" : "belowBar",
              shape: "square",
              color: C.close,
              text: "CLOSE",
            });
          }
        }
      }
      // ANALISIS CHART: BUY saat arah jadi NAIK, SELL saat jadi TURUN, CLOSE saat arah hilang
      if (toggles.analisis && chartRead && chartRead.timeframe === prefs.tf) {
        const wide = el.clientWidth >= MARKER_TEXT_MIN_WIDTH;
        let side: "BUY" | "SELL" | null = null;
        for (const e of chartRead.events) {
          const t = Math.floor(new Date(e.time).getTime() / 1000);
          if (e.action !== "CLOSE") side = e.action;
          if (t < first || t > last) continue;
          if (e.action === "CLOSE") {
            const p = e.result_pips ?? 0;
            marks.push({
              time: ts(t),
              position: side === "BUY" ? "aboveBar" : "belowBar",
              shape: "square",
              color: p > 0 ? C.up : C.down,
              text: `${wide ? "Analisis " : ""}CLOSE ${p > 0 ? "✓" : "✗"}${pipsText(p).trim()}`,
            });
          } else {
            const buy = e.action === "BUY";
            marks.push({
              time: ts(t),
              position: buy ? "belowBar" : "aboveBar",
              shape: buy ? "arrowUp" : "arrowDown",
              color: buy ? C.up : C.down,
              text: `${wide ? "Analisis " : ""}${e.action}${wide ? ` ${e.price.toFixed(digits)}` : ""}`,
            });
          }
        }
      }
      // Pola paling berpotensi: penanda tegas berisi nama + peluang di candle tempat pola muncul
      const hint = patternHint;
      if (toggles.pola && hint && hint.timeframe === prefs.tf && hint.candleTime != null) {
        const at = hint.candleTime;
        if (at >= first && at <= last) {
          const upDir = hint.up != null ? hint.up >= 0.5 : hint.pattern.bias > 0;
          const pct = hint.up != null ? Math.round((upDir ? hint.up : 1 - hint.up) * 100) : null;
          const kept = marks.filter((m) => (m.time as number) !== at || m.shape !== "circle");
          marks.length = 0;
          // Peluang < 55% = lempar koin: titik abu-abu, bukan panah arah
          const decisive = pct != null && pct / 100 >= COIN_FLIP_EDGE;
          marks.push(...kept, {
            time: ts(at),
            position: upDir ? "belowBar" : "aboveBar",
            shape: decisive ? (upDir ? "arrowUp" : "arrowDown") : "circle",
            color: decisive ? (upDir ? C.up : C.down) : C.text,
            text: decisive
              ? `${hint.pattern.name} ${upDir ? "▲" : "▼"}${pct}%`
              : `${hint.pattern.name} ≈${pct != null ? ` ${pct}%` : ""}`,
          });
        }
      }
      createSeriesMarkers(
        series,
        marks.sort((a, b) => (a.time as number) - (b.time as number)),
      );
    }
    // Support & resistance dari analisis chart (sama dengan angka di kartu STRATEGI)
    if (chartRead && chartRead.timeframe === prefs.tf) {
      const level = (price: number | null, color: string, title: string) =>
        price != null &&
        series.createPriceLine({
          price,
          color,
          lineStyle: LineStyle.SparseDotted,
          lineWidth: 1,
          axisLabelVisible: true,
          title,
        });
      level(chartRead.support, C.up, "Support");
      level(chartRead.resistance, C.down, "Resistance");
    }
    for (const sig of signals) {
      if (sig.entry == null) continue;
      // Garis AI: putus-putus jarang (LargeDashed) + label "AI"; strategi: putus-putus biasa
      const style = sig.source === "ai" ? LineStyle.LargeDashed : LineStyle.Dashed;
      const line = (price: number | null, color: string, title: string) =>
        price != null &&
        series.createPriceLine({
          price,
          color,
          lineStyle: style,
          lineWidth: 1,
          axisLabelVisible: true,
          title: tag(sig) + title,
        });
      line(sig.entry, sig.source === "ai" ? C.ai : C.fg, `Entry ${sig.action}`);
      line(sig.trailing_stop ?? sig.stop_loss, C.down, sig.trailing_stop != null ? "SL trail" : "SL");
      if (sig.take_profit_active) line(sig.take_profit, C.up, "TP");
    }

    // Legenda OHLC mengikuti crosshair
    type Ohlc = {
      open: number;
      high: number;
      low: number;
      close: number;
      time: Time;
    };
    const isOhlc = (bar: unknown): bar is Ohlc =>
      typeof bar === "object" && bar !== null && "open" in bar && "close" in bar;
    const setFrom = (c: unknown) =>
      isOhlc(c)
        ? setLegend({
            o: c.open,
            h: c.high,
            l: c.low,
            c: c.close,
            time: c.time as number,
          })
        : setLegend(null);
    setFrom(candles.at(-1));
    chart.subscribeCrosshairMove((param) => {
      const bar = param.time ? param.seriesData.get(series) : undefined;
      hovering.current = Boolean(param.time && param.point);
      setFrom(isOhlc(bar) ? bar : candleSeries.current?.data().at(-1));
    });

    // Pertahankan zoom saat data dimuat ulang pada simbol/timeframe yang sama
    if (savedRange.current?.key === rangeKey && savedRange.current.range) {
      chart.timeScale().setVisibleLogicalRange(savedRange.current.range);
    } else {
      chart.timeScale().setVisibleLogicalRange({
        from: candles.length - 90,
        to: candles.length + 4,
      });
    }

    return () => {
      savedRange.current = {
        key: rangeKey,
        range: chart.timeScale().getVisibleLogicalRange(),
      };
      candleSeries.current = null;
      chartRef.current = null;
      chart.remove();
    };
  }, [data, prefs, digits, signals, history, symbol, onLivePrice, resolved, patternHint, chartRead, prediction]);

  if (!prefs) return <div className="h-[55vh] min-h-[340px] animate-pulse rounded-xl bg-panel" />;

  const toggle = (key: keyof Toggles) =>
    setPrefs({
      ...prefs,
      toggles: { ...prefs.toggles, [key]: !prefs.toggles[key] },
    });

  return (
    <section
      className={
        full
          ? "fixed inset-0 z-50 flex flex-col gap-2 bg-bg px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-[max(0.5rem,env(safe-area-inset-top))]"
          : "space-y-2"
      }
    >
      {/* Dua kelompok utuh: di HP kelompok indikator turun ke baris kedua, tidak terpecah */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="radiogroup" aria-label="Timeframe grafik" className="inline-flex rounded-xl bg-panel p-0.5">
          {TIMEFRAMES.map((t) => (
            <button
              key={t}
              role="radio"
              aria-checked={t === prefs.tf}
              onClick={() => setPrefs({ ...prefs, tf: t })}
              className={`min-w-[44px] rounded-lg px-2.5 py-1.5 text-sm font-semibold ${
                t === prefs.tf ? "bg-panel-2 text-fg shadow-sm" : "text-muted"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <div aria-label="Indikator" className="inline-flex rounded-xl bg-panel p-0.5">
          {(["ema", "bb", "rsi", "macd", "pola", "analisis"] as const).map((k) => (
            <button
              key={k}
              aria-pressed={prefs.toggles[k]}
              onClick={() => toggle(k)}
              className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold uppercase ${
                prefs.toggles[k] ? "bg-panel-2 text-fg shadow-sm" : "text-muted"
              }`}
            >
              {k}
            </button>
          ))}
          <button
            onClick={() => setFull(!full)}
            aria-pressed={full}
            aria-label={full ? "Keluar layar penuh" : "Layar penuh"}
            title={full ? "Keluar layar penuh (Esc)" : "Layar penuh"}
            className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold ${full ? "bg-panel-2 text-fg shadow-sm" : "text-muted"}`}
          >
            {full ? "✕" : "⛶"}
          </button>
        </div>
      </div>

      <div className={full ? "relative min-h-0 flex-1" : "relative"}>
        <div
          ref={container}
          className={`surface w-full overflow-hidden rounded-2xl ${full ? "h-full" : "h-[55vh] min-h-[340px]"}`}
        />
        {/* Legenda dibatasi sebelum skala harga (±76px) agar tidak menimpa label harga */}
        <div className="tabular pointer-events-none absolute left-2 right-[76px] top-1.5 z-10 space-y-0.5 text-[11px] text-muted">
          {legend && (
            <div className="flex flex-wrap gap-x-2">
              <span className="text-fg-soft">
                {symbol} · {prefs.tf}
              </span>
              <span>
                O <b className="font-medium text-fg">{formatPrice(legend.o, digits)}</b>
              </span>
              <span>
                H <b className="font-medium text-fg">{formatPrice(legend.h, digits)}</b>
              </span>
              <span>
                L <b className="font-medium text-fg">{formatPrice(legend.l, digits)}</b>
              </span>
              <span>
                C{" "}
                <b className={`font-medium ${legend.c >= legend.o ? "text-buy" : "text-sell"}`}>
                  {formatPrice(legend.c, digits)}
                </b>
              </span>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px]">
            {data && !data.market_open ? (
              <span className="rounded bg-close/20 px-1.5 py-0.5 font-bold text-close">Pasar tutup</span>
            ) : (
              <span
                className={`flex items-center gap-1 rounded px-1.5 py-0.5 font-bold ${
                  streaming ? "bg-buy/15 text-buy" : "bg-panel-2 text-muted"
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${streaming ? "animate-pulse bg-buy" : "bg-muted"}`} />
                {streaming ? "LIVE" : `±${data?.refresh_seconds ?? 60} dtk`}
              </span>
            )}
            {prefs.toggles.ema && (
              <>
                <span style={{ color: COLORS.ema20 }}>EMA20</span>
                <span style={{ color: COLORS.ema50 }}>EMA50</span>
                <span style={{ color: COLORS.ema200 }}>EMA200</span>
              </>
            )}
          </div>
          <ChartSummary
            read={chartRead}
            hint={prefs.toggles.pola ? patternHint : null}
            window={analysisWindow}
            pred={prefs.toggles.pola ? prediction : null}
            forward={forward}
          />
        </div>
      </div>
      {(error || data?.warning) && <p className="text-xs text-close">{error ?? data?.warning}</p>}
      <p className="text-[11px] text-muted">
        Waktu dalam WIB. Cubit untuk zoom, geser horizontal untuk melihat histori. Indikator diperbarui setiap candle
        tutup;
        {streaming
          ? " harga bergerak real-time (tiap ±1 detik)."
          : ` candle berjalan diperbarui ±${data?.refresh_seconds ?? 60} detik sekali (real-time per detik tidak tersedia untuk ${symbol} di paket data gratis).`}
      </p>
    </section>
  );
}
