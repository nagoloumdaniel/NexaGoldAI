const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3001";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

async function post<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return (await res.json()) as T;
}

export interface Account {
  balance: number;
  nav: number;
  currency: string;
  open_trade_count: number;
  unrealized_pl: number;
}

export interface Summary {
  account: Account | null;
  drawdownPct: number | null;
  decisions: number;
  trades: number;
  openTrades: number;
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Decision {
  time: string;
  strategy: string;
  action: "BUY" | "SELL" | "HOLD";
  confidence: number;
  reason: string;
  executed: boolean;
}

export interface Trade {
  id: string;
  side: "BUY" | "SELL";
  units: number;
  entryPrice: number;
  exitPrice: number | null;
  pnl: number | null;
  status: string;
  strategy: string;
  reason: string;
  openedAt: string;
  closedAt: string | null;
}

export interface ModelVersion {
  id: string;
  config: { horizon: number; threshold: number };
  metrics: {
    value: number;
    accuracy: number;
    sharpe: number;
    profit_factor: number | null;
    samples: number;
  };
}

export interface ModelRegistry {
  granularity: string | null;
  champion: string | null;
  versions: ModelVersion[];
}

export interface Analytics {
  tradeCount: number;
  winRate: number;
  profitFactor: number | null;
  totalPnl: number;
  equityCurve: { time: string; nav: number }[];
}

export interface EngineHealth {
  status: string;
  epic: string;
  capital_env: string;
  trading_enabled: boolean;
  broker_configured: boolean;
  database_connected: boolean;
  ingestion_running: boolean;
}

export interface TradeStatus {
  strategy: string | null;
  trading_enabled: boolean;
  loop_running: boolean;
  interval_seconds: number;
  stop_loss_pct: number;
  risk_reward_ratio: number;
}

export interface SystemStatus {
  engineReachable: boolean;
  engineUrl: string;
  health: EngineHealth | null;
  trade: TradeStatus | null;
}

export interface ReconciliationRow {
  trade_id: string;
  broker_trade_id: string | null;
  broker_deal_id?: string | null;
  side: "BUY" | "SELL";
  units: number;
  status: "matched" | "missing_on_broker" | "closed_from_broker";
  note?: string;
  broker_pnl?: number | null;
  broker_open_level?: number | null;
}

export interface UntrackedBrokerPosition {
  deal_id: string | null;
  deal_reference: string | null;
  instrument: string | null;
  direction: "BUY" | "SELL" | string | null;
  size: number;
  open_level: number;
  pnl: number;
  currency: string | null;
}

export interface ReconciliationStatus {
  engineReachable?: boolean;
  mutated?: boolean;
  close_missing?: boolean;
  db_open_trades: number | null;
  broker_open_positions: number | null;
  matched: number | null;
  closed: number | null;
  missing_on_broker: number | null;
  untracked_broker_positions: number | null;
  closed_trades: {
    trade_id: string;
    exit_price: number;
    pnl: number;
    closed_at: string;
    source: string | null;
  }[];
  unresolved_closures: {
    trade_id: string;
    broker_trade_id: string;
    reason: string;
  }[];
  rows: ReconciliationRow[];
  untracked: UntrackedBrokerPosition[];
}

export interface StructuredSignal {
  engineReachable?: boolean;
  symbol?: string;
  timestamp?: string;
  timeframe?: string;
  direction: "BUY" | "SELL" | "NO_TRADE";
  probability_up?: number;
  probability_down?: number;
  probability_neutral?: number;
  raw_model_score?: number;
  calibrated_confidence?: number;
  uncertainty?: number;
  data_quality_score?: number;
  market_regime?: string;
  expected_move?: number | null;
  expected_value_after_costs?: number | null;
  spread?: number | null;
  slippage_estimate?: number | null;
  recommended_entry?: number | null;
  recommended_sl?: number | null;
  recommended_tp?: number | null;
  risk_reward_ratio?: number | null;
  reasons: string[];
  warnings: string[];
  model_version?: string | null;
  execution_mode?: "PAPER" | "DEMO" | "LIVE" | string;
  math_summary?: {
    simple_return_1: number | null;
    log_return_1: number | null;
    cumulative_return: number | null;
    momentum_3: number | null;
    momentum_12: number | null;
    momentum_acceleration: number | null;
    realised_volatility_20: number | null;
    volatility_ratio_5_20: number | null;
    atr_14: number | null;
    atr_pct_14: number | null;
    zscore_20: number | null;
    regression_slope_20: number | null;
    trend_strength: number | null;
    data_quality_score: number;
    warnings: string[];
  } | null;
  regime_details?: {
    regime: string;
    trend: string;
    volatility: string;
    confidence: number;
    reasons: string[];
    warnings: string[];
  } | null;
  regime_gate?: {
    allowed: boolean;
    status: "ALLOWED" | "BLOCKED" | "NOT_APPLICABLE" | string;
    agreement: "ALIGNED" | "CONFLICT" | "NEUTRAL" | "UNKNOWN" | string;
    reasons: string[];
    warnings: string[];
  } | null;
}

export interface ResolveTradeResult {
  engineReachable?: boolean;
  updated: boolean;
  reason?: string;
  trade_id?: string;
  status?: "CANCELLED" | "CLOSED";
  exit_price?: number;
  pnl?: number;
  closed_at?: string;
}

export const getSummary = () => get<Summary>("/dashboard/summary");
export const getModels = () => get<ModelRegistry>("/dashboard/models");
export const getAnalytics = () => get<Analytics>("/dashboard/analytics");
export const getSystemStatus = () => get<SystemStatus>("/dashboard/system");
export const getStructuredSignal = () =>
  get<StructuredSignal>("/dashboard/signal");
export const getReconciliation = () =>
  get<ReconciliationStatus>("/dashboard/reconciliation");
export const runReconciliation = () =>
  post<ReconciliationStatus>("/dashboard/reconciliation/run");
export const resolveTrade = (
  id: string,
  payload: { status: "CANCELLED" | "CLOSED"; exit_price?: number },
) => post<ResolveTradeResult>(`/dashboard/trades/${id}/resolve`, payload);
export const getCandles = (granularity = "M5", limit = 300) =>
  get<Candle[]>(`/dashboard/candles?granularity=${granularity}&limit=${limit}`);
export const getDecisions = (limit = 50) =>
  get<Decision[]>(`/dashboard/decisions?limit=${limit}`);
export const getTrades = (limit = 50) =>
  get<Trade[]>(`/dashboard/trades?limit=${limit}`);
