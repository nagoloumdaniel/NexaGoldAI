"""Dukascopy historical tick backfill.

Dukascopy publishes one LZMA-compressed `.bi5` file per instrument per hour:
  https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5
(month is 0-indexed in the URL). Each record is 20 bytes, big-endian:
  int32  ms offset from the start of the hour
  int32  ask price in points  (÷ divisor → real price)
  int32  bid price in points
  float32 ask volume
  float32 bid volume

Parsing uses only the standard library (lzma, struct), so it needs no extra
dependency. Ticks are aggregated into OHLCV candles here and stored under the
same instrument key as the live data, giving the backtester one unified series.
"""

import logging
import lzma
import struct
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger("nexagold.dukascopy")

_URL = (
    "https://datafeed.dukascopy.com/datafeed/"
    "{symbol}/{year:04d}/{month:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
)
_TICK = struct.Struct(">iiiff")  # ms, ask, bid, ask_vol, bid_vol

# Granularities whose buckets divide one hour — required for safe per-hour
# aggregation (no candle straddles an hourly file boundary).
_GRAN_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}


def _decompress(raw: bytes) -> bytes:
    try:
        return lzma.decompress(raw)  # FORMAT_AUTO handles the .lzma "alone" format
    except lzma.LZMAError:
        return lzma.decompress(raw, format=lzma.FORMAT_ALONE)


def parse_ticks(raw: bytes, hour_dt: datetime, divisor: float) -> list[tuple]:
    """Decode one bi5 payload into (timestamp, bid, ask) tuples."""
    if not raw:
        return []
    data = _decompress(raw)
    ticks = []
    for offset in range(0, len(data) - (len(data) % _TICK.size), _TICK.size):
        ms, ask, bid, _ask_vol, _bid_vol = _TICK.unpack_from(data, offset)
        ts = hour_dt + timedelta(milliseconds=ms)
        ticks.append((ts, bid / divisor, ask / divisor))
    return ticks


def aggregate_ticks(ticks: list[tuple], granularity: str) -> list[dict]:
    """Resample mid-price ticks into OHLCV candles. Volume = tick count."""
    bucket = _GRAN_SECONDS[granularity]
    candles: dict[int, dict] = {}
    for ts, bid, ask in ticks:
        mid = (bid + ask) / 2
        epoch = int(ts.replace(tzinfo=timezone.utc).timestamp())
        start = epoch - (epoch % bucket)
        candle = candles.get(start)
        if candle is None:
            candles[start] = {"open": mid, "high": mid, "low": mid, "close": mid, "volume": 1}
        else:
            candle["high"] = max(candle["high"], mid)
            candle["low"] = min(candle["low"], mid)
            candle["close"] = mid
            candle["volume"] += 1
    out = []
    for start in sorted(candles):
        c = candles[start]
        t = datetime.fromtimestamp(start, tz=timezone.utc).replace(tzinfo=None)
        out.append(
            {
                "time": t.isoformat(),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
                "complete": True,
            }
        )
    return out


def supported_granularity(granularity: str) -> bool:
    return granularity in _GRAN_SECONDS


class DukascopyClient:
    def __init__(self, symbol: str, divisor: float, timeout: float = 30.0):
        self._symbol = symbol
        self._divisor = divisor
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    def _url(self, hour_dt: datetime) -> str:
        return _URL.format(
            symbol=self._symbol,
            year=hour_dt.year,
            month=hour_dt.month - 1,  # Dukascopy months are 0-indexed
            day=hour_dt.day,
            hour=hour_dt.hour,
        )

    async def fetch_hour(self, hour_dt: datetime) -> list[tuple]:
        """Download and parse one hour of ticks. Missing hours (weekends,
        holidays, not-yet-published) return an empty list."""
        try:
            response = await self._client.get(self._url(hour_dt))
        except httpx.HTTPError as exc:
            logger.warning("Dukascopy %s injoignable: %s", hour_dt, exc)
            return []
        if response.status_code == 404:
            return []
        if response.status_code >= 400:
            logger.warning("Dukascopy %s -> %s", hour_dt, response.status_code)
            return []
        return parse_ticks(response.content, hour_dt, self._divisor)
