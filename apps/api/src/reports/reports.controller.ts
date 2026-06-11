import { Controller, Post } from '@nestjs/common';
import { DailyReportService } from './daily-report.service';

@Controller('reports')
export class ReportsController {
  constructor(private readonly dailyReport: DailyReportService) {}

  // Déclenchement manuel pour tester sans attendre le cron.
  // TODO: protéger par JWT quand le module d'authentification arrivera.
  @Post('daily/run')
  runDaily() {
    return this.dailyReport.sendDailyReport();
  }
}
