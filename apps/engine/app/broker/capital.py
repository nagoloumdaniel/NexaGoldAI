"""Async Capital.com REST client (demo and live).

Docs: https://open-api.capital.com/
Auth flow: POST /session with the API key header returns two session tokens
(CST + X-SECURITY-TOKEN) used for every subsequent call. Tokens expire after
~10 min of inactivity, so requests transparently re-login on 401/403.

Only the endpoints the engine needs are wrapped; responses are normalised to
the same shapes the rest of the engine already expects, so swapping brokers
never touches the strategy or risk code.
"""

from datetime import datetime
from typing import Any

import httpx

from app.config import Settings

# OANDA-style granularity -> Capital.com resolution
_RESOLUTION_MAP = {
    "M1": "MINUTE",
    "M5": "MINUTE_5",
    "M15": "MINUTE_15",
    "M30": "MINUTE_30",
    "H1": "HOUR",
    "H4": "HOUR_4",
    "D": "DAY",
    "W": "WEEK",
}


class CapitalError(Exception):
    """Raised when the Capital.com API returns an error response."""


def _mid(price: dict) -> float:
    """Mid value of a Capital.com {bid, ask} price object."""
    bid = price.get("bid")
    ask = price.get("ask")
    if bid is not None and ask is not None:
        return (float(bid) + float(ask)) / 2
    return float(bid if bid is not None else ask)


class CapitalClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(base_url=settings.capital_base_url, timeout=15.0)
        self._cst: str | None = None
        self._security_token: str | None = None

    async def close(self) -> None:
        await self._client.aclose()

    # -- Auth -----------------------------------------------------------------

    async def _login(self) -> None:
        try:
            response = await self._client.post(
                "/api/v1/session",
                headers={"X-CAP-API-KEY": self._settings.capital_api_key},
                json={
                    "identifier": self._settings.capital_identifier,
                    "password": self._settings.capital_password,
                },
            )
        except httpx.HTTPError as exc:
            raise CapitalError(f"session -> transport error: {exc}") from exc
        if response.status_code >= 400:
            raise CapitalError(f"session -> {response.status_code}: {response.text}")
        self._cst = response.headers.get("CST")
        self._security_token = response.headers.get("X-SECURITY-TOKEN")
        if not self._cst or not self._security_token:
            raise CapitalError("session ouverte mais jetons CST/X-SECURITY-TOKEN absents")

    def _auth_headers(self) -> dict[str, str]:
        return {"CST": self._cst or "", "X-SECURITY-TOKEN": self._security_token or ""}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        extra_headers = kwargs.pop("headers", {})
        if not (self._cst and self._security_token):
            await self._login()
        try:
            response = await self._client.request(
                method, path, headers={**self._auth_headers(), **extra_headers}, **kwargs
            )
            if response.status_code in (401, 403):
                # Session likely expired — re-login once and retry.
                await self._login()
                response = await self._client.request(
                    method, path, headers={**self._auth_headers(), **extra_headers}, **kwargs
                )
        except httpx.HTTPError as exc:
            raise CapitalError(f"{method} {path} -> transport error: {exc}") from exc
        if response.status_code >= 400:
            raise CapitalError(f"{method} {path} -> {response.status_code}: {response.text}")
        return response.json() if response.content else {}

    # -- Market data ----------------------------------------------------------

    async def get_price(self, epic: str | None = None) -> dict:
        """Latest bid/ask for one instrument (default: the configured epic)."""
        epic = epic or self._settings.epic
        data = await self._request("GET", f"/api/v1/markets/{epic}")
        snap = data["snapshot"]
        return {
            "instrument": epic,
            "time": snap.get("updateTime"),
            "bid": float(snap["bid"]),
            "ask": float(snap["offer"]),
            "tradeable": snap.get("marketStatus") == "TRADEABLE",
        }

    @staticmethod
    def _candles_from_response(data: dict) -> list[dict]:
        return [
            {
                "time": c["snapshotTime"],
                "open": _mid(c["openPrice"]),
                "high": _mid(c["highPrice"]),
                "low": _mid(c["lowPrice"]),
                "close": _mid(c["closePrice"]),
                "volume": c.get("lastTradedVolume", 0),
                "complete": True,
            }
            for c in data.get("prices", [])
        ]

    async def get_candles(
        self,
        epic: str | None = None,
        granularity: str = "M1",
        count: int = 200,
    ) -> list[dict]:
        """Most recent mid-price OHLCV candles (Capital.com caps at 1000 per call)."""
        epic = epic or self._settings.epic
        resolution = _RESOLUTION_MAP.get(granularity, granularity)
        data = await self._request(
            "GET",
            f"/api/v1/prices/{epic}",
            params={"resolution": resolution, "max": min(count, 1000)},
        )
        return self._candles_from_response(data)

    async def get_candles_range(
        self,
        granularity: str,
        start: datetime,
        end: datetime,
        epic: str | None = None,
    ) -> list[dict]:
        """Mid-price OHLCV candles between two timestamps (for historical backfill)."""
        epic = epic or self._settings.epic
        resolution = _RESOLUTION_MAP.get(granularity, granularity)
        data = await self._request(
            "GET",
            f"/api/v1/prices/{epic}",
            params={
                "resolution": resolution,
                "from": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "to": end.strftime("%Y-%m-%dT%H:%M:%S"),
                "max": 1000,
            },
        )
        return self._candles_from_response(data)

    # -- Account --------------------------------------------------------------

    async def get_account_summary(self) -> dict:
        """Normalised account snapshot consumed by /account and the daily report."""
        data = await self._request("GET", "/api/v1/accounts")
        accounts = data.get("accounts", [])
        account = next(
            (a for a in accounts if a.get("preferred")),
            accounts[0] if accounts else None,
        )
        if account is None:
            raise CapitalError("Aucun compte Capital.com trouvé")

        balance_info = account["balance"]
        balance = float(balance_info["balance"])
        unrealized_pl = float(balance_info.get("profitLoss") or 0.0)
        positions = await self.get_open_positions()

        return {
            "balance": balance,
            "nav": balance + unrealized_pl,
            "currency": account.get("currency", ""),
            "open_trade_count": len(positions),
            "unrealized_pl": unrealized_pl,
        }

    # -- Orders / positions ---------------------------------------------------

    async def create_market_order(
        self,
        units: float,
        epic: str | None = None,
        stop_loss_price: float | None = None,
        take_profit_price: float | None = None,
    ) -> dict:
        """Market position. Positive units = buy, negative = sell.

        Capital.com expects a positive `size` plus an explicit `direction`,
        unlike OANDA's signed units — the engine keeps using signed units and
        the conversion happens here.
        """
        epic = epic or self._settings.epic
        body: dict[str, Any] = {
            "epic": epic,
            "direction": "BUY" if units > 0 else "SELL",
            "size": abs(units),
        }
        if stop_loss_price is not None:
            body["stopLevel"] = round(stop_loss_price, 2)
        if take_profit_price is not None:
            body["profitLevel"] = round(take_profit_price, 2)
        return await self._request("POST", "/api/v1/positions", json=body)

    async def get_open_positions(self) -> list[dict]:
        data = await self._request("GET", "/api/v1/positions")
        return data.get("positions", [])

    async def close_position(self, epic: str | None = None) -> dict:
        """Close every open position on the given epic (Capital closes per dealId)."""
        epic = epic or self._settings.epic
        closed = []
        for entry in await self.get_open_positions():
            if entry.get("market", {}).get("epic") == epic:
                deal_id = entry.get("position", {}).get("dealId")
                if deal_id:
                    closed.append(await self._request("DELETE", f"/api/v1/positions/{deal_id}"))
        return {"closed": closed}
