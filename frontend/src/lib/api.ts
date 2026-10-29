import type {
  BacktestRequest,
  BacktestRun,
  CandlesResponse,
  ChartRead,
  LiveStats,
  PatternOddsResponse,
  PatternsResponse,
  DashboardResponse,
  DataProviderId,
  DataProviderState,
  Health,
  InstrumentCard,
  InstrumentOut,
  RiskPrefs,
  StrategyStatus,
  SignalView,
  Source,
  Timeframe,
} from "./types";

// Lewat reverse proxy (Caddy): /api/* diteruskan ke backend
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    /** Detik dari header Retry-After (mis. jeda analisis AI), bila ada */
    public retryAfter: number | null = null,
  ) {
    super(message);
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      ...init,
      cache: "no-store",
      headers: { "content-type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("Tidak bisa terhubung ke server", 0);
  }
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail))
        message = body.detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
    } catch {
      // respons bukan JSON
    }
    const retryAfter = Number(res.headers.get("retry-after"));
    throw new ApiError(message, res.status, retryAfter > 0 ? retryAfter : null);
  }
  return (await res.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export const endpoints = {
  dashboard: () => api<DashboardResponse>("/dashboard"),
  card: (symbol: string, source: Source = "rule") =>
    api<InstrumentCard>(`/signals/latest?symbol=${encodeURIComponent(symbol)}&source=${source}`),
  candles: (symbol: string, timeframe: Timeframe, limit = 300) =>
    api<CandlesResponse>(
      `/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=${limit}&indicators=true`,
    ),
  signals: (params: { symbol?: string; source?: Source; limit?: number; beforeId?: number } = {}) => {
    const q = new URLSearchParams({ limit: String(params.limit ?? 30) });
    if (params.symbol) q.set("symbol", params.symbol);
    if (params.source) q.set("source", params.source);
    if (params.beforeId) q.set("before_id", String(params.beforeId));
    return api<SignalView[]>(`/signals?${q}`);
  },
  instruments: () => api<InstrumentOut[]>("/instruments"),
  updateInstrument: (symbol: string, body: { spread_pips?: number | null }) =>
    api<InstrumentOut>(`/instruments/${symbol}/settings`, json("PUT", body)),
  calibrate: (symbol: string, brokerPrice: number) =>
    api<InstrumentOut>(`/instruments/${symbol}/calibrate`, json("POST", { broker_price: brokerPrice })),
  resetCalibration: (symbol: string) =>
    api<InstrumentOut>(`/instruments/${symbol}/calibration`, { method: "DELETE" }),
  risk: () => api<RiskPrefs>("/settings/risk"),
  saveRisk: (prefs: RiskPrefs) => api<RiskPrefs>("/settings/risk", json("PUT", prefs)),
  watchAll: () => api<{ enabled: boolean }>("/settings/watch-all"),
  setWatchAll: (enabled: boolean) => api<{ enabled: boolean }>("/settings/watch-all", json("PUT", { enabled })),
  health: () => api<Health>("/health"),
  dataProvider: () => api<DataProviderState>("/settings/data-provider"),
  setDataProvider: (provider: DataProviderId) =>
    api<DataProviderState>("/settings/data-provider", json("PUT", { provider })),
  stats: (days: number, source: Source = "rule") => api<LiveStats>(`/stats?days=${days}&source=${source}`),
  backtests: () => api<BacktestRun[]>("/backtests"),
  backtest: (id: number) => api<BacktestRun>(`/backtests/${id}`),
  startBacktest: (body: Partial<BacktestRequest>) => api<BacktestRun>("/backtests", json("POST", body)),
  strategyStatus: () => api<StrategyStatus[]>("/strategy/status"),
  runAi: (symbol: string, opts: { votes?: number; timeframe?: Timeframe } = {}) =>
    api<{ card: InstrumentCard; warning: string | null; cooldown_seconds: number }>(
      `/analysis/ai?symbol=${encodeURIComponent(symbol)}${opts.votes ? `&votes=${opts.votes}` : ""}${
        opts.timeframe ? `&timeframe=${opts.timeframe}` : ""
      }`,
      { method: "POST" },
    ),
  aiWarning: (symbol: string) =>
    api<{ warning: string | null }>(`/analysis/ai/warning?symbol=${encodeURIComponent(symbol)}`),
  chartAnalysis: (symbol: string, timeframe: Timeframe) =>
    api<ChartRead>(`/analysis/chart?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`),
  patternOdds: () => api<PatternOddsResponse>("/patterns/stats"),
  patterns: (symbol: string, timeframe?: Timeframe) =>
    api<PatternsResponse>(
      `/patterns?symbol=${encodeURIComponent(symbol)}${timeframe ? `&timeframe=${timeframe}` : ""}`,
    ),
};
