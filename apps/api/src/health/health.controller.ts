import { Controller, Get, ServiceUnavailableException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';

@Controller('health')
export class HealthController {
  constructor(private readonly prisma: PrismaService) {}

  @Get()
  async check() {
    let database = 'ok';
    try {
      await this.prisma.$queryRaw`SELECT 1`;
    } catch {
      database = 'unreachable';
    }
    const payload = {
      status: database === 'ok' ? 'ok' : 'degraded',
      service: 'nexagold-api',
      database,
      timestamp: new Date().toISOString(),
    };
    if (database !== 'ok') {
      // Code HTTP fidèle : un orchestrateur/load-balancer ne doit pas garder
      // une instance sans base de données dans le pool (audit 2026-07-27).
      throw new ServiceUnavailableException(payload);
    }
    return payload;
  }
}
