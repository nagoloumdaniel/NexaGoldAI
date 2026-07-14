"""FRED (Federal Reserve Economic Data) — séries macro journalières.

Le driver n°1 de l'or est le **taux réel US** (rendement réel des TIPS 10 ans,
série FRED `DFII10`) : quand il monte, l'or baisse, et inversement. FRED expose
chaque série en CSV sans clé API :
  https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10&cosd=2023-06-01

Les valeurs manquantes (week-ends, jours fériés) sont marquées "." et ignorées.
Chaque observation journalière est convertie en bougie dégénérée
(open=high=low=close=valeur, volume=0) pour réutiliser le pipeline candles
existant sans schéma dédié.
"""

import logging
from datetime import date

import httpx

logger = logging.getLogger("nexagold.fred")

_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


class FredError(Exception):
    """Raised when FRED returns an error or an unparsable payload."""


class FredClient:
    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch_series(
        self, series_id: str, start: date, end: date | None = None
    ) -> list[dict]:
        """Download one FRED series as a list of daily candle dicts (ascending)."""
        params = {"id": series_id, "cosd": start.isoformat()}
        if end is not None:
            params["coed"] = end.isoformat()
        try:
            response = await self._client.get(_URL, params=params)
        except httpx.HTTPError as exc:
            raise FredError(f"{series_id} -> transport error: {exc}") from exc
        if response.status_code >= 400:
            raise FredError(f"{series_id} -> {response.status_code}: {response.text[:200]}")
        return self._parse_csv(response.text)

    @staticmethod
    def _parse_csv(text: str) -> list[dict]:
        lines = text.strip().splitlines()
        if len(lines) < 2:
            return []
        out: list[dict] = []
        for line in lines[1:]:  # skip header (DATE/observation_date,<series>)
            parts = line.split(",")
            if len(parts) < 2:
                continue
            day, raw = parts[0].strip(), parts[1].strip()
            if not raw or raw == ".":  # FRED marks missing observations with "."
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            out.append(
                {
                    "time": f"{day}T00:00:00",
                    "open": value,
                    "high": value,
                    "low": value,
                    "close": value,
                    "volume": 0,
                }
            )
        return out
