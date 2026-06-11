"""Async OANDA v20 REST client (practice and live).

Docs: https://developer.oanda.com/rest-live-v20/introduction/
Only the endpoints the engine needs are wrapped; everything stays close to the
raw API so responses are easy to cross-check with the official docs.
"""

from typing import Any

import httpx

from app.config import Settings


class OandaError(Exception):
    """Raised when the OANDA API returns an error response."""


class OandaClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.oanda_base_url,
            headers={
                "Authorization": f"Bearer {settings.oanda_api_key}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise OandaError(f"{method} {path} -> {response.status_code}: {response.text}")
        return response.json()

    # -- Account ------------------------------------------------------------

    async def get_account_summary(self) -> dict:
        path = f"/v3/accounts/{self._settings.oanda_account_id}/summary"
        data = await self._request("GET", path)
        return data["account"]

    # -- Market data ----------------------------------------------------------

    async def get_price(self, instrument: str | None = None) -> dict:
        """Latest bid/ask for one instrument (default: the configured one)."""
        instrument = instrument or self._settings.instrument
        path = f"/v3/accounts/{self._settings.oanda_account_id}/pricing"
        data = await self._request("GET", path, params={"instruments": instrument})
        price = data["prices"][0]
        return {
            "instrument": price["instrument"],
            "time": price["time"],
            "bid": float(price["bids"][0]["price"]),
            "ask": float(price["asks"][0]["price"]),
            "tradeable": price["tradeable"],
        }

    async def get_candles(
        self,
        instrument: str | None = None,
        granularity: str = "M1",
        count: int = 500,
    ) -> list[dict]:
        """Recent mid-price OHLCV candles (max 5000 per request)."""
        instrument = instrument or self._settings.instrument
        path = f"/v3/instruments/{instrument}/candles"
        data = await self._request(
            "GET", path, params={"granularity": granularity, "count": count, "price": "M"}
        )
        return [
            {
                "time": c["time"],
                "open": float(c["mid"]["o"]),
                "high": float(c["mid"]["h"]),
                "low": float(c["mid"]["l"]),
                "close": float(c["mid"]["c"]),
                "volume": c["volume"],
                "complete": c["complete"],
            }
            for c in data["candles"]
        ]

    # -- Orders / positions ---------------------------------------------------

    async def create_market_order(
        self,
        units: float,
        instrument: str | None = None,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> dict:
        """Market order. Positive units = buy, negative = sell."""
        instrument = instrument or self._settings.instrument
        order: dict[str, Any] = {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
        }
        if stop_loss_price is not None:
            order["stopLossOnFill"] = {"price": f"{stop_loss_price:.3f}"}
        if take_profit_price is not None:
            order["takeProfitOnFill"] = {"price": f"{take_profit_price:.3f}"}

        path = f"/v3/accounts/{self._settings.oanda_account_id}/orders"
        return await self._request("POST", path, json={"order": order})

    async def get_open_positions(self) -> list[dict]:
        path = f"/v3/accounts/{self._settings.oanda_account_id}/openPositions"
        data = await self._request("GET", path)
        return data["positions"]

    async def close_position(self, instrument: str | None = None) -> dict:
        instrument = instrument or self._settings.instrument
        path = f"/v3/accounts/{self._settings.oanda_account_id}/positions/{instrument}/close"
        return await self._request("PUT", path, json={"longUnits": "ALL", "shortUnits": "ALL"})
