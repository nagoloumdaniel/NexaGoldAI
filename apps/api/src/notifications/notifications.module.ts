import { Module } from '@nestjs/common';
import { AlertsService } from './alerts.service';
import { TelegramService } from './telegram.service';

@Module({
  providers: [TelegramService, AlertsService],
  exports: [TelegramService, AlertsService],
})
export class NotificationsModule {}
