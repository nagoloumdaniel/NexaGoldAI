import {
  CanActivate,
  ExecutionContext,
  Injectable,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import type { Request } from 'express';

/**
 * Garde des routes mutantes (audit 2026-07-27, 2e palier sécurité).
 *
 * - `API_KEY` défini => l'en-tête `x-api-key` doit correspondre, sinon 401.
 * - `API_KEY` absent => autorisé avec avertissement au premier appel :
 *   acceptable uniquement parce que l'API écoute 127.0.0.1 par défaut.
 *   Toute exposition réseau (API_HOST=0.0.0.0, tunnel, Railway) impose de
 *   définir API_KEY.
 */
@Injectable()
export class ApiKeyGuard implements CanActivate {
  private static warned = false;
  private readonly logger = new Logger(ApiKeyGuard.name);

  canActivate(context: ExecutionContext): boolean {
    const expected = process.env.API_KEY;
    if (!expected) {
      if (!ApiKeyGuard.warned) {
        this.logger.warn(
          'API_KEY non défini : routes mutantes sans protection ' +
            '(tolérable seulement en écoute locale 127.0.0.1).',
        );
        ApiKeyGuard.warned = true;
      }
      return true;
    }
    const request = context.switchToHttp().getRequest<Request>();
    if (request.header('x-api-key') !== expected) {
      throw new UnauthorizedException(
        'Clé API absente ou invalide (en-tête x-api-key requis)',
      );
    }
    return true;
  }
}
