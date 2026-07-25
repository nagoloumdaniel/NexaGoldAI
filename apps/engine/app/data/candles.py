"""Candle repository — writes/reads the `Candle` table via asyncpg.

The composite primary key (instrument, granularity, time) makes ingestion
idempotent: re-fetching the same window simply upserts the same rows.
"""

from datetime import datetime, timezone
from decimal import Decimal

import asyncpg

# Identifiers are quoted because Prisma created the table in PascalCase and
# "time" would otherwise collide with reserved usage.
_UPSERT_SQL = """
INSERT INTO "Candle" ("instrument", "granularity", "time", "open", "high", "low", "close", "volume")
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT ("instrument", "granularity", "time") DO UPDATE
SET "open" = EXCLUDED."open",
    "high" = EXCLUDED."high",
    "low" = EXCLUDED."low",
    "close" = EXCLUDED."close",
    "volume" = EXCLUDED."volume"
"""


def _parse_time(value: str) -> datetime:
    """Broker timestamps -> naive UTC datetime (column is TIMESTAMP without tz)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class CandleRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def upsert_many(
        self, instrument: str, granularity: str, candles: list[dict]
    ) -> int:
        if not candles:
            return 0
        records = [
            (
                instrument,
                granularity,
                _parse_time(c["time"]),
                Decimal(str(c["open"])),
                Decimal(str(c["high"])),
                Decimal(str(c["low"])),
                Decimal(str(c["close"])),
                int(c["volume"]),
            )
            for c in candles
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(_UPSERT_SQL, records)
        return len(records)

    async def fetch(self, instrument: str, granularity: str) -> list:
        async with self._pool.acquire() as conn:
            return await conn.fetch(
                'SELECT "time", "open", "high", "low", "close", "volume" '
                'FROM "Candle" WHERE "instrument" = $1 AND "granularity" = $2 '
                'ORDER BY "time"',
                instrument,
                granularity,
            )

    async def stats(self, instrument: str) -> list[dict]:
        """Per-granularity coverage: row count and time range."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT "granularity", COUNT(*) AS count, '
                'MIN("time") AS first, MAX("time") AS last '
                'FROM "Candle" WHERE "instrument" = $1 '
                'GROUP BY "granularity" ORDER BY "granularity"',
                instrument,
            )
        return [
            {
                "granularity": r["granularity"],
                "count": r["count"],
                "first": r["first"].isoformat() if r["first"] else None,
                "last": r["last"].isoformat() if r["last"] else None,
            }
            for r in rows
        ]
