import { Injectable, Logger } from '@nestjs/common';
import { Cron } from '@nestjs/schedule';
import { TelegramService } from '../notifications/telegram.service';
import { PrismaService } from '../prisma/prisma.service';

interface EngineAccount {
  balance: number;
  nav: number;
  currency: string;
  open_trade_count: number;
  unrealized_pl: number;
}

// 21h00 UTC chaque soir ≈ clôture de la journée de trading de l'or
// (17h00 New York en été). Surchargable via REPORT_CRON.
const DEFAULT_CRON = '0 21 * * *';

@Injectable()
export class DailyReportService {
  private readonly logger = new Logger(DailyReportService.name);

  constructor(
    private readonly prisma: PrismaService,
    private readonly telegram: TelegramService,
  ) {}

  @Cron(process.env.REPORT_CRON ?? DEFAULT_CRON, { timeZone: 'UTC' })
  async handleCron() {
    const result = await this.sendDailyReport();
    this.logger.log(`Rapport quotidien: ${JSON.stringify(result)}`);
  }

  async sendDailyReport(): Promise<{ sent: boolean; detail: string }> {
    const account = await this.fetchEngineAccount();
    if (!account) {
      return {
        sent: false,
        detail: 'Moteur ou compte MetaTrader 5 injoignable',
      };
    }

    // Baseline du P&L journalier : le dernier snapshot (celui d'hier soir,
    // puisqu'on en crée un par rapport quotidien).
    const previous = await this.prisma.equitySnapshot.findFirst({
      orderBy: { time: 'desc' },
    });
    const peakAgg = await this.prisma.equitySnapshot.aggregate({
      _max: { nav: true },
    });

    const peakNav = Math.max(Number(peakAgg._max.nav ?? 0), account.nav);
    const drawdownPct =
      peakNav > 0 ? ((peakNav - account.nav) / peakNav) * 100 : 0;

    await this.prisma.equitySnapshot.create({
      data: {
        balance: account.balance,
        nav: account.nav,
        drawdownPct: Math.round(drawdownPct * 1000) / 1000,
      },
    });

    const startOfDay = new Date();
    startOfDay.setUTCHours(0, 0, 0, 0);
    const closedToday = await this.prisma.trade.findMany({
      where: { status: 'CLOSED', closedAt: { gte: startOfDay } },
    });

    const message = this.buildMessage(
      account,
      previous ? Number(previous.nav) : null,
      drawdownPct,
      closedToday.map((t) => Number(t.pnl ?? 0)),
    );

    const sent = await this.telegram.sendMessage(message);
    return {
      sent,
      detail: sent
        ? 'Rapport envoyé sur Telegram'
        : 'Rapport calculé mais non envoyé (Telegram non configuré ou en erreur)',
    };
  }

  // -- Weekly / monthly recaps ------------------------------------------------

  // Vendredi 21h UTC : récap de la semaine (en plus du quotidien).
  @Cron('0 21 * * 5', { timeZone: 'UTC' })
  async handleWeeklyCron() {
    const result = await this.sendWeeklyReport();
    this.logger.log(`Rapport hebdo: ${JSON.stringify(result)}`);
  }

  // 21h UTC les jours 28-31 ; n'envoie que le DERNIER jour du mois.
  @Cron('0 21 28-31 * *', { timeZone: 'UTC' })
  async handleMonthlyCron() {
    const now = new Date();
    const tomorrow = new Date(now);
    tomorrow.setUTCDate(now.getUTCDate() + 1);
    if (tomorrow.getUTCMonth() === now.getUTCMonth()) return; // pas le dernier jour
    const result = await this.sendMonthlyReport();
    this.logger.log(`Rapport mensuel: ${JSON.stringify(result)}`);
  }

  async sendWeeklyReport() {
    const since = new Date();
    since.setUTCDate(since.getUTCDate() - 7);
    return this.sendPeriodReport('Hebdomadaire', '📅', since);
  }

  async sendMonthlyReport() {
    const since = new Date();
    since.setUTCDate(1);
    since.setUTCHours(0, 0, 0, 0);
    return this.sendPeriodReport('Mensuel', '🗓️', since);
  }

  private async sendPeriodReport(
    label: string,
    emoji: string,
    since: Date,
  ): Promise<{ sent: boolean; detail: string }> {
    const account = await this.fetchEngineAccount();
    if (!account) {
      return {
        sent: false,
        detail: 'Moteur ou compte MetaTrader 5 injoignable',
      };
    }

    const snapshots = await this.prisma.equitySnapshot.findMany({
      where: { time: { gte: since } },
      orderBy: { time: 'asc' },
    });
    const startNav = snapshots.length ? Number(snapshots[0].nav) : account.nav;

    // Max drawdown across the period (snapshots + current NAV).
    const navSeries = snapshots.map((s) => Number(s.nav)).concat(account.nav);
    let peak = navSeries[0] ?? account.nav;
    let maxDd = 0;
    for (const nav of navSeries) {
      peak = Math.max(peak, nav);
      if (peak > 0) maxDd = Math.min(maxDd, (nav - peak) / peak);
    }

    const trades = await this.prisma.trade.findMany({
      where: { status: 'CLOSED', closedAt: { gte: since } },
    });

    const message = this.buildPeriodMessage(
      label,
      emoji,
      account,
      startNav,
      maxDd * 100,
      trades.map((t) => Number(t.pnl ?? 0)),
    );
    const sent = await this.telegram.sendMessage(message);
    return {
      sent,
      detail: sent ? `Récap ${label} envoyé` : 'Non envoyé (Telegram)',
    };
  }

  private buildPeriodMessage(
    label: string,
    emoji: string,
    account: EngineAccount,
    startNav: number,
    maxDrawdownPct: number,
    pnls: number[],
  ): string {
    const fmt = (n: number) =>
      n.toLocaleString('fr-FR', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    const signed = (n: number) => `${n >= 0 ? '+' : ''}${fmt(n)}`;

    const periodPnl = account.nav - startNav;
    const periodPct = startNav > 0 ? (periodPnl / startNav) * 100 : 0;
    const wins = pnls.filter((p) => p > 0).length;
    const realized = pnls.reduce((a, b) => a + b, 0);
    const winRate = pnls.length ? (wins / pnls.length) * 100 : 0;

    const lines = [
      `${emoji} <b>NexaGold — Récap ${label}</b>`,
      '',
      `${periodPnl >= 0 ? '📈' : '📉'} Performance : <b>${signed(periodPnl)} ${account.currency}</b> (${signed(periodPct)} %)`,
      `🏦 Équité (NAV) : ${fmt(account.nav)} ${account.currency}`,
      `📉 Drawdown max : ${fmt(maxDrawdownPct)} %`,
      '',
    ];

    if (pnls.length > 0) {
      lines.push(
        `Trades clôturés : ${pnls.length} (taux de réussite ${fmt(winRate)} %)`,
        `P&L réalisé : ${signed(realized)} ${account.currency}`,
      );
    } else {
      lines.push('Aucun trade clôturé sur la période.');
    }

    return lines.join('\n');
  }

  private buildMessage(
    account: EngineAccount,
    previousNav: number | null,
    drawdownPct: number,
    pnls: number[],
  ): string {
    const fmt = (n: number) =>
      n.toLocaleString('fr-FR', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
    const signed = (n: number) => `${n >= 0 ? '+' : ''}${fmt(n)}`;

    const date = new Date().toLocaleDateString('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      timeZone: 'UTC',
    });

    const lines = [`🥇 <b>NexaGold — Rapport du ${date}</b>`, ''];

    if (previousNav !== null) {
      const dayPnl = account.nav - previousNav;
      const dayPct = previousNav > 0 ? (dayPnl / previousNav) * 100 : 0;
      lines.push(
        `${dayPnl >= 0 ? '📈' : '📉'} P&L du jour : <b>${signed(dayPnl)} ${account.currency}</b> (${signed(dayPct)} %)`,
      );
    } else {
      lines.push('📊 Premier rapport — le P&L journalier démarre demain.');
    }

    lines.push(
      `💰 Solde : ${fmt(account.balance)} ${account.currency}`,
      `🏦 Équité (NAV) : ${fmt(account.nav)} ${account.currency}`,
      `📉 Drawdown : ${fmt(drawdownPct)} %`,
      '',
    );

    if (pnls.length > 0) {
      const wins = pnls.filter((p) => p > 0).length;
      const realized = pnls.reduce((a, b) => a + b, 0);
      lines.push(
        `Trades clôturés : ${pnls.length} (${wins} gagnant${wins > 1 ? 's' : ''} / ${pnls.length - wins} perdant${pnls.length - wins > 1 ? 's' : ''})`,
        `P&L réalisé : ${signed(realized)} ${account.currency}`,
      );
    } else {
      lines.push('Aucun trade clôturé aujourd’hui.');
    }

    if (account.open_trade_count > 0) {
      lines.push(
        `Positions ouvertes : ${account.open_trade_count} (P&L latent : ${signed(account.unrealized_pl)} ${account.currency})`,
      );
    }

    return lines.join('\n');
  }

  private async fetchEngineAccount(): Promise<EngineAccount | null> {
    const engineUrl = process.env.ENGINE_URL ?? 'http://localhost:8000';
    try {
      const response = await fetch(`${engineUrl}/account`, {
        signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok) {
        this.logger.error(
          `Le moteur a répondu ${response.status} sur /account`,
        );
        return null;
      }
      return (await response.json()) as EngineAccount;
    } catch (error) {
      this.logger.error(`Moteur injoignable (${engineUrl}): ${String(error)}`);
      return null;
    }
  }
}
