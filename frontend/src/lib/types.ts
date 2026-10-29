// Tipe data mengikuti model Pydantic di backend (app/services/views.py, app/api/*.py)

export type Action = "BUY" | "SELL" | "CLOSE" | "WAIT";
export type EntryState = "VALID" | "EXPIRED_TIME" | "EXPIRED_DISTANCE" | "CLOSED";
export type Source = "rule" | "ai";
export type Timeframe = "M1" | "M5" | "M15" | "H1" | "H4";

export const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "H1", "H4"];
export const TF_SECONDS: Record<Timeframe, number> = {
  M1: 60,
  M5: 300,
  M15: 900,
  H1: 3600,
  H4: 14400,
};

export interface InstrumentOut {
  symbol: string;
  name: string;
  asset_class: string;
  pip_size: number;
  digits: number;
  contract_size: number;
  spread_pips: number;
  spread_is_custom: boolean;
  signal_validity_pips: number;
  price_offset: number;
  price_offset_pips: number;
  broker_price: number | null;
  feed_price: number | null;
  calibrated_at: string | null;
  market_open: boolean;
  next_open: string | null;
}

export interface SignalView {
  id: number;
  /** rule = strategi teruji backtest, ai = AI Groq (eksperimen) */
  source: Source;
  symbol: string;
  instrument_name: string;
  digits: number;
  pip_size: number;
  action: Exclude<Action, "WAIT">;
  closes_action: "BUY" | "SELL" | null;
  parent_id: number | null;
  strategy: string;
  signal_time: string;
  created_at: string;
  price_offset: number;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  sl_pips: number | null;
  tp_pips: number | null;
  risk_reward: number | null;
  spread_pips: number | null;
  confidence: number | null;
  confidence_label: string | null;
  reason_text: string;
  reasons: string[];
  status: "ACTIVE" | "EXPIRED" | "HIT_TP" | "HIT_SL" | "CLOSED";
  status_label: string;
  entry_state: EntryState;
  entry_state_label: string;
  entry_valid_until: string | null;
  validity_pips: number;
  current_price: number | null;
  price_source: string | null;
  price_updated_at: string | null;
  distance_from_entry_pips: number | null;
  capital: number | null;
  risk_percent: number;
  risk_amount: number | null;
  suggested_lot: number | null;
  closed_at: string | null;
  close_price: number | null;
  close_reason: string | null;
  result_pips: number | null;
}

export interface AnalysisOut {
  analyzed_at: string;
  candle_time: string | null;
  reasons: string[];
  filters: string[];
  details: Record<string, unknown>;
}

export interface InstrumentCard {
  source: Source;
  instrument: InstrumentOut;
  action: Action;
  is_new_event: boolean;
  analysis: AnalysisOut | null;
  signal: SignalView | null;
  current_price: number | null;
  price_source: string | null;
  price_updated_at: string | null;
  next_candle_close: string;
}

export interface RiskPrefs {
  capital: number | null;
  risk_percent: number;
}

export interface DashboardResponse {
  server_time: string;
  next_candle_close: string;
  seconds_to_next_candle: number;
  risk: RiskPrefs;
  cards: InstrumentCard[];
  ai_enabled: boolean;
  ai_cards: InstrumentCard[];
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface IndicatorPoint {
  time: number;
  value: number;
}

export interface CandlesResponse {
  symbol: string;
  timeframe: Timeframe;
  market_open: boolean;
  live: Candle | null;
  live_updated_at: string | null;
  refresh_seconds: number;
  warning: string | null;
  adjusted: boolean;
  price_offset: number;
  candles: Candle[];
  indicators: Record<string, IndicatorPoint[]> | null;
  patterns: PatternMark[] | null;
}

export interface Health {
  status: string;
  data_provider: string;
  database: boolean;
  redis: boolean;
  worker_last_heartbeat: string | null;
  instruments: string[];
  server_time: string;
  next_m15_close: string;
}

export type LiveMessage = {
  type: "live";
  symbol: string;
  timeframe: Timeframe;
  candle: Candle | null;
  updated_at: string | null;
  market_open: boolean;
  warning: string | null;
  /** true = harga real-time per detik (WebSocket Twelve Data) */
  streaming?: boolean;
};

export type WsMessage =
  | { type: "hello"; server_time: string; next_candle_close: string; refresh_seconds: number }
  | { type: "card"; data: InstrumentCard }
  | { type: "signal"; data: SignalView }
  | LiveMessage
  | { type: "pong" }
  | { type: "error"; message: string };

export interface Metrics {
  trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  net_pips: number;
  avg_win_pips: number | null;
  avg_loss_pips: number | null;
  total_r: number;
  expectancy_r: number | null;
  profit_factor: number | null;
  avg_rr_planned: number | null;
  avg_rr_realized: number | null;
  max_drawdown_r: number;
  max_drawdown_pct: number;
  return_pct: number;
  sharpe: number | null;
  by_status: Record<string, number>;
}

export type PeriodMetrics = Metrics & { start: string; end: string };

export interface EquityPoint {
  time: number;
  equity: number;
}

export interface BacktestSection {
  all: Metrics;
  in_sample: PeriodMetrics;
  out_of_sample: PeriodMetrics;
  windows: PeriodMetrics[];
  equity: EquityPoint[];
}

export interface BacktestInstrument extends BacktestSection {
  strategy?: { name: string; params: Record<string, unknown> };
  coverage: Record<string, { candles: number; first: string | null; last: string | null }>;
  costs: { spread_pips: number; slippage_pips: number };
  trades: {
    action: string;
    entry_time: string;
    exit_time: string;
    status: string;
    result_pips: number;
    r: number;
    close_reason: string | null;
  }[];
  optimization?: {
    note: string;
    best_params: Record<string, number>;
    best_in_sample: Metrics;
    best_out_of_sample: Metrics;
  };
}

export interface BacktestSummary {
  period: { start: string; end: string; days: number };
  strategy: { name: string; params: Record<string, unknown> };
  settings: BacktestRequest;
  notes: string[];
  portfolio: BacktestSection;
  instruments: Record<string, BacktestInstrument>;
}

export interface BacktestRequest {
  symbols: string[] | null;
  days: number;
  in_sample_ratio: number;
  windows: number;
  risk_percent: number;
  optimize: boolean;
}

export interface BacktestRun {
  id: number;
  status: "queued" | "running" | "done" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  request: BacktestRequest;
  error: string | null;
  summary?: BacktestSummary | null;
}

export interface LiveStats {
  days: number;
  source: Source;
  risk_percent: number;
  overall: Metrics;
  instruments: Record<string, Metrics>;
  equity: EquityPoint[];
}

export interface StrategyStatus {
  symbol: string;
  strategy: string;
  tested: boolean;
  validated: boolean;
  reason: string;
  backtest_id: number | null;
  tested_at: string | null;
  out_of_sample: {
    trades: number;
    win_rate: number | null;
    profit_factor: number | null;
    expectancy_r: number | null;
    total_r: number;
  } | null;
}

export interface PatternOut {
  name: string;
  /** 1 = potensi naik, -1 = potensi turun, 0 = ragu-ragu */
  bias: number;
  meaning: string;
  /** 1 lemah, 2 sedang, 3 kuat (0 = netral) */
  strength: number;
  strength_text: string;
  note: string;
}

export interface PatternMark extends PatternOut {
  time: number;
}

export interface PatternsResponse {
  symbol: string;
  timeframes: { timeframe: Timeframe; trend: string; candle_time: number | null; patterns: PatternOut[] }[];
  conclusion: { bias: "BUY" | "SELL" | "MIXED" | "NONE"; text: string };
}
