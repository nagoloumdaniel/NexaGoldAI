import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

const ENGINE_URL = process.env.ENGINE_URL ?? 'http://localhost:8000';
// Clé instrument des bougies en base — le moteur écrit sous settings.symbol
// (XAUUSD depuis la migration MT5, ex-GOLD chez Capital.com).
const INSTRUMENT = process.env.INSTRUMENT_KEY ?? 'XAUUSD';

@Injectable()
export class DashboardService {
  constructor(private readonly prisma: PrismaService) {}

  private async engine<T>(path: string): Promise<T | null> {
    try {
      const res = await fetch(`${ENGINE_URL}${path}`, {
        signal: AbortSignal.timeout(8000),
      });
      if (!res.ok) return null;
      return (await res.json()) as T;
    } catch {
      return null;
    }
  }

  private async enginePost<T>(
    path: string,
    body?: Record<string, unknown>,
  ): Promise<T | null> {
    try {
      const res = await fetch(`${ENGINE_URL}${path}`, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(20_000),
      });
      if (!res.ok) return null;
      return (await res.json()) as T;
    } catch {
      return null;
    }
  }

  async summary() {
    const [account, decisions, trades, openTrades, lastEquity] =
      await Promise.all([
        this.engine<Record<string, unknown>>('/account'),
        this.prisma.strategyDecision.count(),
        this.prisma.trade.count(),
        this.prisma.trade.count({ where: { status: 'OPEN' } }),
        this.prisma.equitySnapshot.findFirst({ orderBy: { time: 'desc' } }),
      ]);
    return {
      account,
      drawdownPct: lastEquity?.drawdownPct
        ? Number(lastEquity.drawdownPct)
        : null,
      decisions,
      trades,
      openTrades,
    };
  }

  async candles(granularity: string, limit: number) {
    const rows = await this.prisma.candle.findMany({
      where: { instrument: INSTRUMENT, granularity },
      orderBy: { time: 'desc' },
      take: limit,
    });
    return rows.reverse().map((c) => ({
      time: c.time.toISOString(),
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),
      volume: c.volume,
    }));
  }

  async decisions(limit: number) {
    const rows = await this.prisma.strategyDecision.findMany({
      orderBy: { time: 'desc' },
      take: limit,
    });
    return rows.map((d) => ({
      time: d.time.toISOString(),
      strategy: d.strategy,
      action: d.action,
      confidence: Number(d.confidence),
      reason: d.reason,
      features: d.features,
      tradeId: d.tradeId,
      executed: d.executed,
    }));
  }

  async trades(limit: number) {
    const rows = await this.prisma.trade.findMany({
      orderBy: { openedAt: 'desc' },
      take: limit,
    });
    return rows.map((t) => ({
      id: t.id,
      side: t.side,
      units: Number(t.units),
      entryPrice: Number(t.entryPrice),
      exitPrice: t.exitPrice ? Number(t.exitPrice) : null,
      pnl: t.pnl ? Number(t.pnl) : null,
      status: t.status,
      strategy: t.strategy,
      reason: t.reason,
      openedAt: t.openedAt.toISOString(),
      closedAt: t.closedAt ? t.closedAt.toISOString() : null,
    }));
  }

  async positions() {
    return (await this.engine<unknown[]>('/positions')) ?? [];
  }

  async models() {
    return (
      (await this.engine<Record<string, unknown>>('/learning/registry')) ?? {
        granularity: null,
        champion: null,
        versions: [],
      }
    );
  }

  async paperValidation() {
    return (
      (await this.engine<Record<string, unknown>>('/paper/validation')) ?? {
        strategy: 'expected-return-paper',
        closed_trades: 0,
        target_closed_trades: 100,
        progress: 0,
        eligible_for_review: false,
        automatic_live_promotion: false,
      }
    );
  }

  async regimeShadow() {
    return (
      (await this.engine<Record<string, unknown>>('/paper/regime-shadow')) ?? {
        strategy: 'expected-return-paper-regime-shadow',
        filter: 'exclude_regime:BULLISH_TREND',
        total_decisions: 0,
        filtered_decisions: 0,
        kept_decisions: 0,
        filter_rate: 0,
        execution_enabled: false,
      }
    );
  }

  async promotionEligibility() {
    return (
      (await this.engine<Record<string, unknown>>(
        '/paper/promotion-eligibility',
      )) ?? {
        strategy: 'expected-return-paper',
        promotion_eligible: false,
        review_eligible: false,
        automatic_live_promotion: false,
        broker_env: 'demo',
        trading_enabled: false,
        paper_only: true,
        checked_at: null,
        requirements: [
          {
            code: 'ENGINE_UNREACHABLE',
            label: 'Moteur joignable',
            passed: false,
            detail: 'Moteur injoignable; promotion impossible.',
          },
        ],
        blockers: [
          {
            code: 'ENGINE_UNREACHABLE',
            label: 'Moteur joignable',
            passed: false,
            detail: 'Moteur injoignable; promotion impossible.',
          },
        ],
      }
    );
  }

  async analytics() {
    const closed = await this.prisma.trade.findMany({
      where: { status: 'CLOSED' },
    });
    const pnls = closed.map((t) => Number(t.pnl ?? 0));
    const wins = pnls.filter((p) => p > 0);
    const grossWin = wins.reduce((a, b) => a + b, 0);
    const grossLoss = Math.abs(
      pnls.filter((p) => p < 0).reduce((a, b) => a + b, 0),
    );
    const equity = await this.prisma.equitySnapshot.findMany({
      orderBy: { time: 'asc' },
      take: 500,
    });
    return {
      tradeCount: closed.length,
      winRate: pnls.length ? wins.length / pnls.length : 0,
      profitFactor: grossLoss > 0 ? grossWin / grossLoss : null,
      totalPnl: pnls.reduce((a, b) => a + b, 0),
      equityCurve: equity.map((e) => ({
        time: e.time.toISOString(),
        nav: Number(e.nav),
      })),
    };
  }

  async system() {
    const [health, trade] = await Promise.all([
      this.engine<Record<string, unknown>>('/health'),
      this.engine<Record<string, unknown>>('/trade/status'),
    ]);

    return {
      engineReachable: health !== null,
      engineUrl: ENGINE_URL,
      health,
      trade,
    };
  }

  async signal() {
    return (
      (await this.engine<Record<string, unknown>>('/signal/latest')) ?? {
        engineReachable: false,
        direction: 'NO_TRADE',
        reasons: ['Moteur injoignable ou signal indisponible'],
        warnings: [],
      }
    );
  }

  async reconciliation() {
    return (
      (await this.engine<Record<string, unknown>>(
        '/trades/reconciliation',
      )) ?? {
        engineReachable: false,
        db_open_trades: null,
        broker_open_positions: null,
        matched: null,
        closed: null,
        missing_on_broker: null,
        untracked_broker_positions: null,
        closed_trades: [],
        unresolved_closures: [],
        rows: [],
        untracked: [],
      }
    );
  }

  async runReconciliation() {
    return (
      (await this.enginePost<Record<string, unknown>>(
        '/trades/reconcile?close_missing=true',
      )) ?? {
        engineReachable: false,
        mutated: false,
        close_missing: true,
        db_open_trades: null,
        broker_open_positions: null,
        matched: null,
        closed: null,
        missing_on_broker: null,
        untracked_broker_positions: null,
        updated: [],
        closed_trades: [],
        unresolved_closures: [],
        rows: [],
        untracked: [],
      }
    );
  }

  async resolveTrade(
    id: string,
    body: {
      status: 'CANCELLED' | 'CLOSED';
      exit_price?: number;
      closed_at?: string;
    },
  ) {
    return (
      (await this.enginePost<Record<string, unknown>>(
        `/trades/${encodeURIComponent(id)}/resolve`,
        body,
      )) ?? {
        engineReachable: false,
        updated: false,
        reason: 'Moteur injoignable ou resolution refusee',
      }
    );
  }
}
