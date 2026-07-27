"""Ingestion service: MetaTrader 5 -> `Candle` table.

Two modes:
- ingest_recent(): refresh the latest candles for each configured granularity.
  Run on a timer; idempotent, so re-running when the market is closed is a no-op.
- backfill(): walk a date range backwards in <=1000-candle windows to seed
  history for backtesting.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.broker.mt5 import BrokerError, MT5Client
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
        broker: MT5Client,
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

    async def stats(self, instrument: str | None = None) -> list[dict]:
        return await self._repository.stats(instrument or self._settings.symbol)

    async def stored_candles(
        self, granularity: str, limit: int, instrument: str | None = None
    ) -> list[dict]:
        """Dernières bougies stockées en base, au format dict du moteur."""
        rows = await self._repository.fetch(
            instrument or self._settings.symbol, granularity
        )
        return [
            {
                "time": r["time"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["volume"]),
            }
            for r in rows[-limit:]
        ]

    async def ingest_recent(self) -> dict[str, int]:
        """Upsert the latest candles for every configured granularity."""
        result: dict[str, int] = {}
        for granularity in self._granularities:
            candles = await self._broker.get_candles(
                granularity=granularity, count=self._settings.ingest_recent_count
            )
            result[granularity] = await self._repository.upsert_many(
                self._settings.symbol, granularity, candles
            )
        return result

    async def backfill(self, granularity: str, days: int) -> int:
        """Seed `days` of history for one granularity, paginating by window."""
        minutes = _GRAN_MINUTES.get(granularity, 1)
        # Fenêtres de 900 bougies : borne la taille des réponses MT5 et permet
        # de reprendre là où une fenêtre a échoué.
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
            except BrokerError as exc:
                logger.warning("Backfill %s window failed: %s", granularity, exc)
                cursor = window_end
                continue
            total += await self._repository.upsert_many(
                self._settings.symbol, granularity, candles
            )
            cursor = window_end
        logger.info("Backfill %s sur %d j -> %d bougies", granularity, days, total)
        return total

    async def backfill_dukascopy(
        self,
        granularity: str,
        days: int,
        concurrency: int = 12,
        symbol: str | None = None,
        divisor: float | None = None,
        instrument: str | None = None,
    ) -> dict:
        """Seed deep history from Dukascopy tick files.

        Hours are downloaded concurrently in batches, then aggregated and
        upserted batch by batch so memory stays bounded regardless of range.
        `symbol`/`divisor`/`instrument` override the defaults to backfill a
        secondary instrument (e.g. a macro proxy).
        """
        if not supported_granularity(granularity):
            raise ValueError(
                f"Granularité {granularity} non supportée par Dukascopy "
                "(utiliser M1, M5, M15, M30 ou H1)"
            )
        symbol = symbol or self._settings.dukascopy_symbol
        divisor = divisor if divisor is not None else self._settings.dukascopy_price_divisor
        instrument = instrument or self._settings.symbol
        client = DukascopyClient(symbol, divisor)
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
                for _hour_dt, ticks in fetched:
                    scanned += 1
                    if not ticks:
                        continue
                    with_data += 1
                    ticks_total += len(ticks)
                    candles = aggregate_ticks(ticks, granularity)
                    candles_total += await self._repository.upsert_many(
                        instrument, granularity, candles
                    )
        finally:
            await client.close()

        summary = {
            "instrument": instrument,
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

    async def resample(
        self, source: str, target: str, instrument: str | None = None
    ) -> dict:
        """Build coarser candles (e.g. H1) from finer ones (e.g. M5) already in
        the DB — no re-download needed."""
        import pandas as pd  # local import: keeps engine startup light

        rule = {"M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h", "D": "1D"}.get(
            target
        )
        if rule is None:
            raise ValueError(f"Cible {target} non supportée pour le resampling")

        instrument = instrument or self._settings.symbol
        rows = await self._repository.fetch(instrument, source)
        if not rows:
            return {"error": f"Aucune bougie source {source} pour {instrument}"}

        df = pd.DataFrame([dict(r) for r in rows])
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(int)
        df = df.set_index(pd.to_datetime(df["time"])).sort_index()

        agg = (
            df.resample(rule)
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        candles = [
            {
                "time": idx.isoformat(),
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": int(row.volume),
            }
            for idx, row in agg.iterrows()
        ]
        upserted = await self._repository.upsert_many(instrument, target, candles)
        return {
            "instrument": instrument,
            "source": source,
            "target": target,
            "candles": upserted,
        }

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
            except BrokerError as exc:
                logger.warning("Ingestion ignorée (broker): %s", exc)
            except Exception:  # noqa: BLE001 — the loop must never die silently
                logger.exception("Erreur inattendue dans la boucle d'ingestion")
            await asyncio.sleep(interval)
