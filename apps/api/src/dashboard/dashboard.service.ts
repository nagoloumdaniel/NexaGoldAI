import { Injectable } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

const ENGINE_URL = process.env.ENGINE_URL ?? 'http://localhost:8000';
const INSTRUMENT = 'GOLD';

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
      drawdownPct: lastEquity?.drawdownPct ? Number(lastEquity.drawdownPct) : null,
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
}
