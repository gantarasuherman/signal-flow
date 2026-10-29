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
import { useCallback, useEffect, useRef, useState } from "react";
import { endpoints } from "@/lib/api";
import { dateTimeWIB, dayMonthWIB, formatPrice, monthWIB, timeWIB, yearWIB } from "@/lib/format";
import { useRealtime, useRealtimeMessages } from "@/lib/realtime";
import { readPalette, useTheme } from "@/lib/theme";
import {
  TF_SECONDS,
  TIMEFRAMES,
  type CandlesResponse,
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

type Toggles = { ema: boolean; bb: boolean; rsi: boolean; macd: boolean; pola: boolean };
const DEFAULT_TOGGLES: Toggles = { ema: true, bb: false, rsi: true, macd: false, pola: true };
const STORAGE_KEY = "signalflow:chart";

function loadPrefs(): { tf: Timeframe; toggles: Toggles } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { tf?: Timeframe; toggles?: Partial<Toggles> };
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

function buildMarkers(
  signals: SignalView[],
  tf: Timeframe,
  first: number,
  last: number,
  colors: { up: string; down: string; close: string } = COLORS,
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = [];
  for (const s of signals) {
    const time = markerTime(s.signal_time, tf);
    if (time < first || time > last) continue;
    if (s.action === "BUY")
      markers.push({ time: ts(time), position: "belowBar", shape: "arrowUp", color: colors.up, text: `${tag(s)}BUY` });
    else if (s.action === "SELL")
      markers.push({ time: ts(time), position: "aboveBar", shape: "arrowDown", color: colors.down, text: `${tag(s)}SELL` });
    else markers.push({ time: ts(time), position: "aboveBar", shape: "circle", color: colors.close, text: `${tag(s)}CLOSE` });
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
}

export default function PriceChart({
  symbol,
  digits,
  signals,
  history,
  reloadKey,
  onLivePrice,
  onTimeframe,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeries = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lastBarTime = useRef(0);
  const savedRange = useRef<{ key: string; range: LogicalRange | null } | null>(null);
  const [prefs, setPrefs] = useState<{ tf: Timeframe; toggles: Toggles } | null>(null);
  const [data, setData] = useState<CandlesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [legend, setLegend] = useState<{ o: number; h: number; l: number; c: number; time: number } | null>(null);
  const [streaming, setStreaming] = useState(false);
  const hovering = useRef(false);
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
          setLegend({ o: c.open, h: c.high, l: c.low, c: c.close, time: c.time });
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
        { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...extra },
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
      const rsi = line("rsi", "#a78bfa", pane, { lastValueVisible: true, priceFormat: { type: "price", precision: 1, minMove: 0.1 } });
      rsi?.createPriceLine({ price: 70, color: C.line, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
      rsi?.createPriceLine({ price: 30, color: C.line, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
      pane += 1;
    }
    if (toggles.macd && ind.macd_hist?.length) {
      const hist = chart.addSeries(
        HistogramSeries,
        { priceLineVisible: false, lastValueVisible: false, priceFormat: { type: "price", precision: digits + 1, minMove: 10 ** -(digits + 1) } },
        pane,
      );
      hist.setData(
        ind.macd_hist.map((p) => ({ time: ts(p.time), value: p.value, color: p.value >= 0 ? `${C.up}99` : `${C.down}99` })),
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
      const marks = buildMarkers(history, prefs.tf, first, last, C);
      if (toggles.pola && data.patterns) marks.push(...patternMarkers(data.patterns, C, el.clientWidth >= MARKER_TEXT_MIN_WIDTH));
      createSeriesMarkers(
        series,
        marks.sort((a, b) => (a.time as number) - (b.time as number)),
      );
    }
    for (const sig of signals) {
      if (sig.entry == null) continue;
      // Garis AI: putus-putus jarang (LargeDashed) + label "AI"; strategi: putus-putus biasa
      const style = sig.source === "ai" ? LineStyle.LargeDashed : LineStyle.Dashed;
      const line = (price: number | null, color: string, title: string) =>
        price != null &&
        series.createPriceLine({ price, color, lineStyle: style, lineWidth: 1, axisLabelVisible: true, title: tag(sig) + title });
      line(sig.entry, sig.source === "ai" ? C.ai : C.fg, `Entry ${sig.action}`);
      line(sig.trailing_stop ?? sig.stop_loss, C.down, sig.trailing_stop != null ? "SL trail" : "SL");
      if (sig.take_profit_active) line(sig.take_profit, C.up, "TP");
    }

    // Legenda OHLC mengikuti crosshair
    type Ohlc = { open: number; high: number; low: number; close: number; time: Time };
    const isOhlc = (bar: unknown): bar is Ohlc =>
      typeof bar === "object" && bar !== null && "open" in bar && "close" in bar;
    const setFrom = (c: unknown) =>
      isOhlc(c) ? setLegend({ o: c.open, h: c.high, l: c.low, c: c.close, time: c.time as number }) : setLegend(null);
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
      chart.timeScale().setVisibleLogicalRange({ from: candles.length - 90, to: candles.length + 4 });
    }

    return () => {
      savedRange.current = { key: rangeKey, range: chart.timeScale().getVisibleLogicalRange() };
      candleSeries.current = null;
      chartRef.current = null;
      chart.remove();
    };
  }, [data, prefs, digits, signals, history, symbol, onLivePrice, resolved]);

  if (!prefs) return <div className="h-[55vh] min-h-[340px] animate-pulse rounded-xl bg-panel" />;

  const toggle = (key: keyof Toggles) => setPrefs({ ...prefs, toggles: { ...prefs.toggles, [key]: !prefs.toggles[key] } });

  return (
    <section className="space-y-2">
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
          {(["ema", "bb", "rsi", "macd", "pola"] as const).map((k) => (
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
        </div>
      </div>

      <div className="relative">
        <div
          ref={container}
          className="surface h-[55vh] min-h-[340px] w-full overflow-hidden rounded-2xl"
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
        </div>
      </div>
      {(error || data?.warning) && <p className="text-xs text-close">{error ?? data?.warning}</p>}
      <p className="text-[11px] text-muted">
        Waktu dalam WIB. Cubit untuk zoom, geser horizontal untuk melihat histori. Indikator diperbarui setiap candle tutup;
        {streaming
          ? " harga bergerak real-time (tiap ±1 detik)."
          : ` candle berjalan diperbarui ±${data?.refresh_seconds ?? 60} detik sekali (real-time per detik tidak tersedia untuk ${symbol} di paket data gratis).`}
      </p>
    </section>
  );
}
