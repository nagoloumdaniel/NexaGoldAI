"""Standalone Dukascopy backfill (no server needed).

Usage:
  .venv\\Scripts\\python.exe -m app.data.backfill_cli --granularity M5 --days 365
"""

import argparse
import asyncio

from app.broker.capital import CapitalClient
from app.config import get_settings
from app.data.candles import CandleRepository
from app.data.ingestion import IngestionService
from app.db import Database


async def run(granularity: str, days: int, concurrency: int) -> None:
    settings = get_settings()
    db = Database(settings)
    await db.connect()
    if not db.is_connected:
        print("Base de données indisponible (DATABASE_URL)")
        return
    broker = CapitalClient(settings)  # unused by the Dukascopy path, closed below
    service = IngestionService(settings, broker, CandleRepository(db.pool))
    try:
        result = await service.backfill_dukascopy(granularity, days, concurrency)
        print(result)
    finally:
        await broker.close()
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Dukascopy")
    parser.add_argument("--granularity", default="M5")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()
    asyncio.run(run(args.granularity, args.days, args.concurrency))


if __name__ == "__main__":
    main()
