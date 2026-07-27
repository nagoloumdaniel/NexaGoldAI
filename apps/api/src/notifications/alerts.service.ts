import { Injectable, Logger } from '@nestjs/common';
import { Cron, CronExpression } from '@nestjs/schedule';
import { PrismaService } from '../prisma/prisma.service';
import { TelegramService } from './telegram.service';

// Seules ces gravités déclenchent une alerte : les événements INFO restent
// consultables dans le dashboard sans réveiller personne.
const ALERTED_SEVERITIES = ['WARNING', 'CRITICAL'];
// Les événements plus anciens ne sont jamais envoyés (redémarrage tardif,
// Telegram configuré après coup) : ils sont marqués notifiés sans envoi.
const MAX_AGE_MINUTES = 180;
const BATCH_SIZE = 20;

const TITLES: Record<string, string> = {
  KILL_SWITCH_LOCK: '🛑 KILL SWITCH VERROUILLÉ',
  KILL_SWITCH_UNLOCK: '🔓 Kill switch déverrouillé',
  BROKER_DEGRADED: '⚠️ Connexion broker dégradée',
  BROKER_RECOVERED: '✅ Connexion broker rétablie',
  ANOMALY: '⚠️ Anomalie détectée',
};

interface AlertEvent {
  id: string;
  eventType: string;
  severity: string;
  component: string;
  message: string;
  time: Date;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');
}

@Injectable()
export class AlertsService {
  private readonly logger = new Logger(AlertsService.name);

  constructor(
    private readonly prisma: PrismaService,
    private readonly telegram: TelegramService,
  ) {}

  /** Relais des événements moteur vers Telegram. Le moteur écrit en base,
   * l'API notifie : le token reste à un seul endroit et rien n'est perdu si
   * l'API redémarre. */
  @Cron(CronExpression.EVERY_MINUTE)
  async flushPendingAlerts(): Promise<{ sent: number; skipped: number }> {
    let events: AlertEvent[];
    try {
      events = await this.prisma.systemEvent.findMany({
        where: { notified: false, severity: { in: ALERTED_SEVERITIES } },
        orderBy: { time: 'asc' },
        take: BATCH_SIZE,
        select: {
          id: true,
          eventType: true,
          severity: true,
          component: true,
          message: true,
          time: true,
        },
      });
    } catch (error) {
      this.logger.warn(`Lecture des événements impossible: ${String(error)}`);
      return { sent: 0, skipped: 0 };
    }
    if (events.length === 0) return { sent: 0, skipped: 0 };

    const cutoff = new Date(Date.now() - MAX_AGE_MINUTES * 60_000);
    let sent = 0;
    let skipped = 0;

    for (const event of events) {
      if (event.time < cutoff) {
        // Périmé : on marque sans envoyer pour ne pas alerter sur du passé.
        await this.markNotified(event.id);
        skipped += 1;
        continue;
      }
      const ok = await this.telegram.sendMessage(this.buildMessage(event));
      if (!ok) {
        // Telegram indisponible/non configuré : on laisse l'événement en
        // attente, il repartira au prochain passage.
        break;
      }
      await this.markNotified(event.id);
      sent += 1;
    }

    if (sent > 0 || skipped > 0) {
      this.logger.log(`Alertes: ${sent} envoyée(s), ${skipped} périmée(s)`);
    }
    return { sent, skipped };
  }

  private async markNotified(id: string): Promise<void> {
    try {
      await this.prisma.systemEvent.update({
        where: { id },
        data: { notified: true },
      });
    } catch (error) {
      this.logger.warn(
        `Marquage de l'alerte ${id} impossible: ${String(error)}`,
      );
    }
  }

  buildMessage(event: {
    eventType: string;
    severity: string;
    component: string;
    message: string;
    time: Date;
  }): string {
    const title = TITLES[event.eventType] ?? `⚠️ ${event.eventType}`;
    const when = event.time.toLocaleString('fr-FR', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'UTC',
    });
    const lines = [
      `<b>${title}</b>`,
      '',
      `<b>Quand</b> : ${when} UTC`,
      `<b>Composant</b> : ${escapeHtml(event.component)}`,
      `<b>Détail</b> : ${escapeHtml(event.message)}`,
    ];
    if (event.eventType === 'KILL_SWITCH_LOCK') {
      lines.push(
        '',
        'Aucun nouvel ordre ne sera envoyé.',
        'Réactivation manuelle explicite requise après analyse.',
      );
    }
    return lines.join('\n');
  }
}
