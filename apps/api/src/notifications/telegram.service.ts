import { Injectable, Logger } from '@nestjs/common';

@Injectable()
export class TelegramService {
  private readonly logger = new Logger(TelegramService.name);

  get isConfigured(): boolean {
    return Boolean(
      process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_CHAT_ID,
    );
  }

  async sendMessage(text: string): Promise<boolean> {
    if (!this.isConfigured) {
      this.logger.warn(
        'TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID manquants — notification ignorée',
      );
      return false;
    }

    const token = process.env.TELEGRAM_BOT_TOKEN;
    const url = `https://api.telegram.org/bot${token}/sendMessage`;
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chat_id: process.env.TELEGRAM_CHAT_ID,
          text,
          parse_mode: 'HTML',
        }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok) {
        this.logger.error(
          `Telegram a répondu ${response.status}: ${await response.text()}`,
        );
        return false;
      }
      return true;
    } catch (error) {
      this.logger.error(`Envoi Telegram impossible: ${String(error)}`);
      return false;
    }
  }
}
