import { Controller, Post, UseGuards } from '@nestjs/common';
import { ApiKeyGuard } from '../auth/api-key.guard';
import { DailyReportService } from './daily-report.service';

// Déclenchement manuel des rapports (stop-auto.ps1 et tests). Protégé par
// clé d'API quand API_KEY est défini — sinon n'importe qui joignant l'API
// pourrait spammer Telegram et écrire des EquitySnapshot.
@Controller('reports')
@UseGuards(ApiKeyGuard)
export class ReportsController {
  constructor(private readonly dailyReport: DailyReportService) {}

  @Post('daily/run')
  runDaily() {
    return this.dailyReport.sendDailyReport();
  }

  @Post('weekly/run')
  runWeekly() {
    return this.dailyReport.sendWeeklyReport();
  }

  @Post('monthly/run')
  runMonthly() {
    return this.dailyReport.sendMonthlyReport();
  }
}
