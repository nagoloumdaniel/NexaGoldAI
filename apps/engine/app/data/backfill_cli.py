"""Standalone Dukascopy backfill (no server needed).

Usage:
  .venv\\Scripts\\python.exe -m app.data.backfill_cli --granularity M5 --days 365
"""

import argparse
import asyncio

from app.broker.mt5 import MT5Client
from app.config import get_settings
from app.data.candles import CandleRepository
from app.data.ingestion import IngestionService
from app.db import Database


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings)
    await db.connect()
    if not db.is_connected:
        print("Base de données indisponible (DATABASE_URL)")
        return
    broker = MT5Client(settings)  # unused by the Dukascopy path, closed below
    service = IngestionService(settings, broker, CandleRepository(db.pool))
    try:
        result = await service.backfill_dukascopy(
            args.granularity,
            args.days,
            args.concurrency,
            symbol=args.symbol,
            divisor=args.divisor,
            instrument=args.instrument,
        )
        print(result)
    finally:
        await broker.close()
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Dukascopy")
    parser.add_argument("--granularity", default="M5")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--concurrency", type=int, default=16)
    # Overrides to backfill a secondary instrument (e.g. a macro proxy).
    parser.add_argument("--symbol", default=None, help="Symbole Dukascopy (ex. EURUSD)")
    parser.add_argument("--divisor", type=float, default=None, help="Diviseur de prix")
    parser.add_argument("--instrument", default=None, help="Clé instrument en base")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
