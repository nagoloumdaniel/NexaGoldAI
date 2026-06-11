"""NexaGold trading engine — FastAPI service.

Exposes health/market endpoints for the NestJS backend and hosts the trading
loop (data -> strategy -> risk -> execution). The loop itself ships in the
next iteration; this scaffold already wires OANDA connectivity end to end.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.broker.oanda import OandaClient, OandaError
from app.config import get_settings

settings = get_settings()
oanda: OandaClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global oanda
    oanda = OandaClient(settings)
    yield
    await oanda.close()


app = FastAPI(title="NexaGold Engine", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "instrument": settings.instrument,
        "oanda_env": settings.oanda_env,
        "trading_enabled": settings.trading_enabled,
        "oanda_configured": bool(settings.oanda_api_key and settings.oanda_account_id),
    }


def ensure_oanda_configured() -> None:
    if not (settings.oanda_api_key and settings.oanda_account_id):
        raise HTTPException(
            status_code=503,
            detail="OANDA non configuré : renseignez OANDA_API_KEY et OANDA_ACCOUNT_ID",
        )


@app.get("/market/price")
async def market_price() -> dict:
    ensure_oanda_configured()
    try:
        return await oanda.get_price()
    except OandaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/market/candles")
async def market_candles(granularity: str = "M1", count: int = 200) -> list[dict]:
    ensure_oanda_configured()
    try:
        return await oanda.get_candles(granularity=granularity, count=min(count, 5000))
    except OandaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/account")
async def account() -> dict:
    ensure_oanda_configured()
    try:
        summary = await oanda.get_account_summary()
    except OandaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "balance": float(summary["balance"]),
        "nav": float(summary["NAV"]),
        "currency": summary["currency"],
        "open_trade_count": summary["openTradeCount"],
        "unrealized_pl": float(summary["unrealizedPL"]),
    }
