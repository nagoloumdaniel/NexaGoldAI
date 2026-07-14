import { Body, Controller, Get, Param, Post, Query } from '@nestjs/common';
import { DashboardService } from './dashboard.service';

const clamp = (value: string | undefined, fallback: number, max: number) =>
  Math.min(Number(value) || fallback, max);

@Controller('dashboard')
export class DashboardController {
  constructor(private readonly dashboard: DashboardService) {}

  @Get('summary')
  summary() {
    return this.dashboard.summary();
  }

  @Get('candles')
  candles(
    @Query('granularity') granularity = 'M5',
    @Query('limit') limit?: string,
  ) {
    return this.dashboard.candles(granularity, clamp(limit, 300, 1000));
  }

  @Get('decisions')
  decisions(@Query('limit') limit?: string) {
    return this.dashboard.decisions(clamp(limit, 50, 200));
  }

  @Get('trades')
  trades(@Query('limit') limit?: string) {
    return this.dashboard.trades(clamp(limit, 50, 200));
  }

  @Get('positions')
  positions() {
    return this.dashboard.positions();
  }

  @Get('models')
  models() {
    return this.dashboard.models();
  }

  @Get('paper-validation')
  paperValidation() {
    return this.dashboard.paperValidation();
  }

  @Get('analytics')
  analytics() {
    return this.dashboard.analytics();
  }

  @Get('system')
  system() {
    return this.dashboard.system();
  }

  @Get('signal')
  signal() {
    return this.dashboard.signal();
  }

  @Get('reconciliation')
  reconciliation() {
    return this.dashboard.reconciliation();
  }

  @Post('reconciliation/run')
  runReconciliation() {
    return this.dashboard.runReconciliation();
  }

  @Post('trades/:id/resolve')
  resolveTrade(
    @Param('id') id: string,
    @Body()
    body: {
      status: 'CANCELLED' | 'CLOSED';
      exit_price?: number;
      closed_at?: string;
    },
  ) {
    return this.dashboard.resolveTrade(id, body);
  }
}
