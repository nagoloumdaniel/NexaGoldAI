import { Controller, Get, Query } from '@nestjs/common';
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

  @Get('analytics')
  analytics() {
    return this.dashboard.analytics();
  }
}
