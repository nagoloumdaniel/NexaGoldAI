import { AlertsService } from './alerts.service';
import type { PrismaService } from '../prisma/prisma.service';
import type { TelegramService } from './telegram.service';

type EventRow = {
  id: string;
  eventType: string;
  severity: string;
  component: string;
  message: string;
  time: Date;
};

function makeService(events: EventRow[], sendResult = true) {
  const updated: string[] = [];
  const sentMessages: string[] = [];
  const prisma = {
    systemEvent: {
      findMany: jest.fn().mockResolvedValue(events),
      update: jest.fn(({ where }: { where: { id: string } }) => {
        updated.push(where.id);
        return Promise.resolve({});
      }),
    },
  } as unknown as PrismaService;
  const telegram = {
    sendMessage: jest.fn((text: string) => {
      sentMessages.push(text);
      return Promise.resolve(sendResult);
    }),
  } as unknown as TelegramService;
  return {
    service: new AlertsService(prisma, telegram),
    updated,
    sentMessages,
    prisma,
    telegram,
  };
}

function event(overrides: Partial<EventRow> = {}): EventRow {
  return {
    id: 'se_1',
    eventType: 'KILL_SWITCH_LOCK',
    severity: 'CRITICAL',
    component: 'trader',
    message: 'Perte quotidienne atteinte',
    time: new Date(),
    ...overrides,
  };
}

describe('AlertsService', () => {
  it('envoie les alertes récentes et les marque notifiées', async () => {
    const { service, updated, sentMessages } = makeService([event()]);
    const result = await service.flushPendingAlerts();
    expect(result).toEqual({ sent: 1, skipped: 0 });
    expect(updated).toEqual(['se_1']);
    expect(sentMessages[0]).toContain('KILL SWITCH VERROUILLÉ');
    expect(sentMessages[0]).toContain('Perte quotidienne atteinte');
  });

  it('marque sans envoyer les événements périmés', async () => {
    const old = new Date(Date.now() - 5 * 60 * 60 * 1000);
    const { service, updated, sentMessages } = makeService([
      event({ id: 'se_old', time: old }),
    ]);
    const result = await service.flushPendingAlerts();
    expect(result).toEqual({ sent: 0, skipped: 1 });
    expect(updated).toEqual(['se_old']);
    expect(sentMessages).toHaveLength(0);
  });

  it("laisse l'événement en attente si Telegram échoue", async () => {
    const { service, updated } = makeService([event()], false);
    const result = await service.flushPendingAlerts();
    expect(result).toEqual({ sent: 0, skipped: 0 });
    expect(updated).toHaveLength(0); // réessayé au prochain passage
  });

  it('ne remonte rien quand la base est injoignable', async () => {
    const prisma = {
      systemEvent: {
        findMany: jest.fn().mockRejectedValue(new Error('db down')),
        update: jest.fn(),
      },
    } as unknown as PrismaService;
    const telegram = { sendMessage: jest.fn() } as unknown as TelegramService;
    const service = new AlertsService(prisma, telegram);
    await expect(service.flushPendingAlerts()).resolves.toEqual({
      sent: 0,
      skipped: 0,
    });
  });

  it('échappe le HTML du message', () => {
    const { service } = makeService([]);
    const message = service.buildMessage(
      event({ message: 'spread <b>anormal</b> & large' }),
    );
    expect(message).toContain('&lt;b&gt;anormal&lt;/b&gt; &amp; large');
  });
});
