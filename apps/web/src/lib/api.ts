const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3001";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
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

export const getSummary = () => get<Summary>("/dashboard/summary");
export const getModels = () => get<ModelRegistry>("/dashboard/models");
export const getCandles = (granularity = "M5", limit = 300) =>
  get<Candle[]>(`/dashboard/candles?granularity=${granularity}&limit=${limit}`);
export const getDecisions = (limit = 50) =>
  get<Decision[]>(`/dashboard/decisions?limit=${limit}`);
export const getTrades = (limit = 50) =>
  get<Trade[]>(`/dashboard/trades?limit=${limit}`);
