"""NexaGold trading engine — FastAPI service.

Exposes health/market endpoints for the NestJS backend and hosts the trading
loop (data -> strategy -> risk -> execution). The loop itself ships in the
next iteration; this scaffold already wires Capital.com connectivity end to end.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.broker.capital import CapitalClient, CapitalError
from app.config import get_settings

settings = get_settings()
broker: CapitalClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global broker
    broker = CapitalClient(settings)
    yield
    await broker.close()


app = FastAPI(title="NexaGold Engine", version="0.1.0", lifespan=lifespan)


def ensure_broker_configured() -> None:
    if not (
        settings.capital_api_key
        and settings.capital_identifier
        and settings.capital_password
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Capital.com non configuré : renseignez CAPITAL_API_KEY, "
                "CAPITAL_IDENTIFIER et CAPITAL_PASSWORD"
            ),
        )


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "epic": settings.epic,
        "capital_env": settings.capital_env,
        "trading_enabled": settings.trading_enabled,
        "broker_configured": bool(
            settings.capital_api_key
            and settings.capital_identifier
            and settings.capital_password
        ),
    }


@app.get("/market/price")
async def market_price() -> dict:
    ensure_broker_configured()
    try:
        return await broker.get_price()
    except CapitalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/market/candles")
async def market_candles(granularity: str = "M1", count: int = 200) -> list[dict]:
    ensure_broker_configured()
    try:
        return await broker.get_candles(granularity=granularity, count=min(count, 1000))
    except CapitalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/account")
async def account() -> dict:
    ensure_broker_configured()
    try:
        return await broker.get_account_summary()
    except CapitalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
