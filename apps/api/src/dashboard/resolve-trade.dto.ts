import {
  IsIn,
  IsISO8601,
  IsNumber,
  IsOptional,
  IsPositive,
} from 'class-validator';

// Corps de POST /dashboard/trades/:id/resolve — validé ici avant d'être
// transmis au moteur (qui garde ses propres vérifications métier).
export class ResolveTradeDto {
  @IsIn(['CANCELLED', 'CLOSED'])
  status!: 'CANCELLED' | 'CLOSED';

  @IsOptional()
  @IsNumber()
  @IsPositive()
  exit_price?: number;

  @IsOptional()
  @IsISO8601()
  closed_at?: string;
}
