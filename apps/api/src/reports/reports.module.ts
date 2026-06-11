import { Module } from '@nestjs/common';
import { NotificationsModule } from '../notifications/notifications.module';
import { DailyReportService } from './daily-report.service';
import { ReportsController } from './reports.controller';

@Module({
  imports: [NotificationsModule],
  controllers: [ReportsController],
  providers: [DailyReportService],
})
export class ReportsModule {}
