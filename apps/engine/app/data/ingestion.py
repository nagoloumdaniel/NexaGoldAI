"""Ingestion service: Capital.com -> `Candle` table.

Two modes:
- ingest_recent(): refresh the latest candles for each configured granularity.
  Run on a timer; idempotent, so re-running when the market is closed is a no-op.
- backfill(): walk a date range backwards in <=1000-candle windows to seed
  history for backtesting.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.broker.capital import CapitalClient, CapitalError
from app.config import Settings
from app.data.candles import CandleRepository
from app.data.dukascopy import DukascopyClient, aggregate_ticks, supported_granularity

logger = logging.getLogger("nexagold.ingestion")

# Minutes covered by one candle of each granularity — used to size backfill windows.
_GRAN_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D": 1440,
    "W": 10080,
}


class IngestionService:
    def __init__(
        self,
        settings: Settings,
        broker: CapitalClient,
        repository: CandleRepository,
    ):
        self._settings = settings
        self._broker = broker
        self._repository = repository
        self._granularities = [
            g.strip() for g in settings.ingest_granularities.split(",") if g.strip()
        ]

    @property
    def granularities(self) -> list[str]:
        return self._granularities

    async def stats(self) -> list[dict]:
        return await self._repository.stats(self._settings.epic)

    async def ingest_recent(self) -> dict[str, int]:
        """Upsert the latest candles for every configured granularity."""
        result: dict[str, int] = {}
        for granularity in self._granularities:
            candles = await self._broker.get_candles(
                granularity=granularity, count=self._settings.ingest_recent_count
            )
            result[granularity] = await self._repository.upsert_many(
                self._settings.epic, granularity, candles
            )
        return result

    async def backfill(self, granularity: str, days: int) -> int:
        """Seed `days` of history for one granularity, paginating by window."""
        minutes = _GRAN_MINUTES.get(granularity, 1)
        # 900 candles/window keeps a margin under Capital.com's 1000 cap.
        window = timedelta(minutes=minutes * 900)
        end = datetime.now(timezone.utc)
        cursor = end - timedelta(days=days)
        total = 0
        while cursor < end:
            window_end = min(cursor + window, end)
            try:
                candles = await self._broker.get_candles_range(
                    granularity, cursor, window_end
                )
            except CapitalError as exc:
                logger.warning("Backfill %s window failed: %s", granularity, exc)
                cursor = window_end
                continue
            total += await self._repository.upsert_many(
                self._settings.epic, granularity, candles
            )
            cursor = window_end
        logger.info("Backfill %s sur %d j -> %d bougies", granularity, days, total)
        return total

    async def backfill_dukascopy(
        self, granularity: str, days: int, concurrency: int = 12
    ) -> dict:
        """Seed deep history from Dukascopy tick files.

        Hours are downloaded concurrently in batches, then aggregated and
        upserted batch by batch so memory stays bounded regardless of range.
        """
        if not supported_granularity(granularity):
            raise ValueError(
                f"Granularité {granularity} non supportée par Dukascopy "
                "(utiliser M1, M5, M15, M30 ou H1)"
            )
        client = DukascopyClient(
            self._settings.dukascopy_symbol, self._settings.dukascopy_price_divisor
        )
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        hours = [
            start + timedelta(hours=i)
            for i in range(int((end - start).total_seconds() // 3600))
        ]

        scanned = 0
        with_data = 0
        ticks_total = 0
        candles_total = 0
        try:
            for i in range(0, len(hours), concurrency):
                batch = hours[i : i + concurrency]
                fetched = await asyncio.gather(
                    *(self._fetch_hour(client, h) for h in batch)
                )
                for hour_dt, ticks in fetched:
                    scanned += 1
                    if not ticks:
                        continue
                    with_data += 1
                    ticks_total += len(ticks)
                    candles = aggregate_ticks(ticks, granularity)
                    candles_total += await self._repository.upsert_many(
                        self._settings.epic, granularity, candles
                    )
        finally:
            await client.close()

        summary = {
            "granularity": granularity,
            "days": days,
            "hours_scanned": scanned,
            "hours_with_data": with_data,
            "ticks": ticks_total,
            "candles_upserted": candles_total,
        }
        logger.info("Backfill Dukascopy: %s", summary)
        return summary

    @staticmethod
    async def _fetch_hour(client: DukascopyClient, hour_dt: datetime) -> tuple:
        return hour_dt, await client.fetch_hour(hour_dt)

    async def run_loop(self) -> None:
        """Background task: ingest_recent() on a fixed interval until cancelled."""
        interval = self._settings.ingest_interval_seconds
        logger.info(
            "Ingestion démarrée (%s, toutes les %ss)",
            ",".join(self._granularities),
            interval,
        )
        while True:
            try:
                result = await self.ingest_recent()
                logger.info("Ingestion: %s", result)
            except CapitalError as exc:
                logger.warning("Ingestion ignorée (broker): %s", exc)
            except Exception:  # noqa: BLE001 — the loop must never die silently
                logger.exception("Erreur inattendue dans la boucle d'ingestion")
            await asyncio.sleep(interval)
