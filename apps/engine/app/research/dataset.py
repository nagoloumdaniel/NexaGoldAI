"""Load candles from the `Candle` table into a pandas DataFrame for research."""

import asyncpg
import pandas as pd

from app.config import Settings

_NUMERIC = ["open", "high", "low", "close", "volume"]


def _to_frame(rows: list) -> pd.DataFrame:
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    for col in _NUMERIC:
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["time"])
    return df.set_index("time").sort_index()


async def load_candles(
    settings: Settings, granularity: str, instrument: str | None = None
) -> pd.DataFrame:
    instrument = instrument or settings.epic
    conn = await asyncpg.connect(settings.database_url)
    try:
        rows = await conn.fetch(
            'SELECT "time", "open", "high", "low", "close", "volume" '
            'FROM "Candle" WHERE "instrument" = $1 AND "granularity" = $2 '
            'ORDER BY "time"',
            instrument,
            granularity,
        )
    finally:
        await conn.close()
    return _to_frame(rows)


def candles_to_frame(candles: list[dict]) -> pd.DataFrame:
    """Convert engine candle dicts (broker/repository shape) to the same frame."""
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame(candles)
    for col in _NUMERIC:
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["time"])
    return df.set_index("time").sort_index()
