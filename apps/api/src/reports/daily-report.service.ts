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

// 21h00 UTC du lundi au vendredi ≈ clôture de la journée de trading de l'or
// (17h00 New York en été). Surchargable via REPORT_CRON.
const DEFAULT_CRON = '0 21 * * 1-5';

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
      return { sent: false, detail: 'Moteur ou compte OANDA injoignable' };
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
