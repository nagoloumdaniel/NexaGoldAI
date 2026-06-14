"""NexaGold trading engine — FastAPI service.

Exposes health/market endpoints for the NestJS backend and runs the data
pipeline (Capital.com -> `Candle` table). The strategy/risk/execution loop
ships in the next phase; market connectivity and ingestion are wired here.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from app.broker.capital import CapitalClient, CapitalError
from app.config import get_settings
from app.data.candles import CandleRepository
from app.data.ingestion import IngestionService
from app.db import Database

settings = get_settings()

broker: CapitalClient | None = None
database: Database | None = None
ingestion: IngestionService | None = None
_ingestion_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global broker, database, ingestion, _ingestion_task

    broker = CapitalClient(settings)
    database = Database(settings)
    await database.connect()

    if database.is_connected:
        repository = CandleRepository(database.pool)
        ingestion = IngestionService(settings, broker, repository)
        broker_ready = bool(
            settings.capital_api_key
            and settings.capital_identifier
            and settings.capital_password
        )
        if settings.ingest_enabled and broker_ready:
            _ingestion_task = asyncio.create_task(ingestion.run_loop())

    yield

    if _ingestion_task is not None:
        _ingestion_task.cancel()
        try:
            await _ingestion_task
        except asyncio.CancelledError:
            pass
    await broker.close()
    await database.close()


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


def ensure_ingestion_ready() -> IngestionService:
    if ingestion is None:
        raise HTTPException(
            status_code=503,
            detail="Base de données indisponible : DATABASE_URL non configuré ou injoignable",
        )
    return ingestion


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
        "database_connected": database.is_connected if database else False,
        "ingestion_running": _ingestion_task is not None and not _ingestion_task.done(),
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


# -- Data pipeline ----------------------------------------------------------


@app.post("/ingest/run")
async def ingest_run() -> dict:
    """Trigger one immediate refresh of the latest candles (all granularities)."""
    ensure_broker_configured()
    service = ensure_ingestion_ready()
    try:
        return {"upserted": await service.ingest_recent()}
    except CapitalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/ingest/backfill")
async def ingest_backfill(
    granularity: str = Query("M5"),
    days: int = Query(2, ge=1, le=60),
) -> dict:
    """Seed historical candles for one granularity over the last `days` days."""
    ensure_broker_configured()
    service = ensure_ingestion_ready()
    try:
        upserted = await service.backfill(granularity, days)
    except CapitalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"granularity": granularity, "days": days, "upserted": upserted}


@app.get("/candles/stats")
async def candles_stats() -> dict:
    service = ensure_ingestion_ready()
    return {"instrument": settings.epic, "granularities": await service.stats()}
