"""NexaGold trading engine — FastAPI service.

Exposes health/market endpoints for the NestJS backend and runs both the data
pipeline (Capital.com -> `Candle` table) and the paper-trading loop
(data -> signal -> risk -> order, gated by the TRADING_ENABLED kill switch).
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from app.broker.capital import CapitalClient, CapitalError
from app.config import get_settings
from app.data.candles import CandleRepository
from app.data.decisions import StrategyDecisionRepository
from app.data.ingestion import IngestionService
from app.data.trades import TradeRepository
from app.db import Database
from app.execution.trader import Trader
from app.learning.registry import ModelRegistry
from app.learning.service import LearningService
from app.risk.manager import RiskManager
from app.strategy.factory import build_strategy

settings = get_settings()

broker: CapitalClient | None = None
database: Database | None = None
ingestion: IngestionService | None = None
trader: Trader | None = None
decisions_repo: StrategyDecisionRepository | None = None
learning: LearningService | None = None
_ingestion_task: asyncio.Task | None = None
_trade_task: asyncio.Task | None = None
_learning_task: asyncio.Task | None = None


def _broker_ready() -> bool:
    return bool(
        settings.capital_api_key
        and settings.capital_identifier
        and settings.capital_password
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global broker, database, ingestion, trader, decisions_repo, learning
    global _ingestion_task, _trade_task, _learning_task

    broker = CapitalClient(settings)
    database = Database(settings)
    await database.connect()

    if database.is_connected:
        ingestion = IngestionService(settings, broker, CandleRepository(database.pool))
        decisions_repo = StrategyDecisionRepository(database.pool)
        trader = Trader(
            settings,
            broker,
            build_strategy(settings),
            RiskManager(settings),
            decisions_repo,
            TradeRepository(database.pool, settings.epic),
        )
        learning = LearningService(settings, trader)
        if _broker_ready():
            if settings.ingest_enabled:
                _ingestion_task = asyncio.create_task(ingestion.run_loop())
            if settings.trading_loop_enabled:
                _trade_task = asyncio.create_task(trader.run_loop())
        if settings.learning_enabled:
            _learning_task = asyncio.create_task(learning.run_loop())

    yield

    for task in (_ingestion_task, _trade_task, _learning_task):
        if task is not None:
            task.cancel()
            try:
                await task
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


@app.get("/positions")
async def positions() -> list[dict]:
    ensure_broker_configured()
    try:
        raw = await broker.get_open_positions()
    except CapitalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    out = []
    for entry in raw:
        pos = entry.get("position", {})
        market = entry.get("market", {})
        out.append(
            {
                "instrument": market.get("epic"),
                "direction": pos.get("direction"),
                "size": pos.get("size"),
                "open_level": pos.get("level"),
                "pnl": pos.get("upl"),
                "currency": pos.get("currency"),
            }
        )
    return out


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


@app.post("/ingest/dukascopy")
async def ingest_dukascopy(
    granularity: str = Query("M5"),
    days: int = Query(1, ge=1, le=30),
) -> dict:
    """Backfill deep history from Dukascopy tick data (M1/M5/M15/M30/H1)."""
    service = ensure_ingestion_ready()
    try:
        return await service.backfill_dukascopy(granularity, days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/candles/stats")
async def candles_stats() -> dict:
    service = ensure_ingestion_ready()
    return {"instrument": settings.epic, "granularities": await service.stats()}


# -- Paper trading ----------------------------------------------------------


@app.post("/trade/step")
async def trade_step() -> dict:
    """Run one loop iteration: data -> signal -> risk -> (order if enabled)."""
    ensure_broker_configured()
    if trader is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    try:
        return await trader.step()
    except CapitalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/trade/status")
async def trade_status() -> dict:
    return {
        "strategy": trader.strategy_name if trader else None,
        "trading_enabled": settings.trading_enabled,
        "loop_running": _trade_task is not None and not _trade_task.done(),
        "interval_seconds": settings.trade_interval_seconds,
        "stop_loss_pct": settings.stop_loss_pct,
        "risk_reward_ratio": settings.risk_reward_ratio,
    }


@app.get("/decisions/recent")
async def decisions_recent(limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    if decisions_repo is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    return await decisions_repo.recent(limit)


# -- Learning loop ----------------------------------------------------------


@app.post("/learning/retrain")
async def learning_retrain() -> dict:
    """Run one retraining round: candidate configs compete, best is promoted."""
    if learning is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    return await learning.retrain_once()


@app.get("/learning/registry")
async def learning_registry() -> dict:
    registry = ModelRegistry(
        Path(__file__).resolve().parents[1] / "models", settings.model_granularity
    )
    return {
        "granularity": settings.model_granularity,
        "champion": registry.champion(),
        "versions": registry.versions(),
    }
