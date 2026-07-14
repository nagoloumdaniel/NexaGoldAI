"""Backfill d'une série macro FRED (taux réels, dollar, etc.) dans la table Candle.

Usage:
  .venv\\Scripts\\python.exe -m app.data.fred_cli --series DFII10 --days 1095
  (par défaut : DFII10 = taux réel US 10 ans, le driver n°1 de l'or)

La série est stockée sous granularité "D" et la clé instrument = --series, donc
load_candles(settings, "D", instrument="DFII10") la relit telle quelle.
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.data.candles import CandleRepository
from app.data.fred import FredClient
from app.db import Database


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings)
    await db.connect()
    if not db.is_connected:
        print("Base de données indisponible (DATABASE_URL)")
        return
    repo = CandleRepository(db.pool)
    client = FredClient()
    try:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=args.days)
        candles = await client.fetch_series(args.series, start, end)
        upserted = await repo.upsert_many(args.instrument or args.series, "D", candles)
        print(
            {
                "series": args.series,
                "instrument": args.instrument or args.series,
                "observations": len(candles),
                "upserted": upserted,
                "range": [candles[0]["time"][:10], candles[-1]["time"][:10]]
                if candles
                else [],
            }
        )
    finally:
        await client.close()
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill série macro FRED")
    parser.add_argument("--series", default="DFII10", help="ID série FRED (ex. DFII10)")
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument(
        "--instrument", default=None, help="Clé instrument en base (défaut: =série)"
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
