"""NexaGold trading engine — FastAPI service.

Exposes health/market endpoints for the NestJS backend and runs both the data
pipeline (MetaTrader 5 -> `Candle` table) and the paper-trading loop
(data -> signal -> risk -> order, gated by the TRADING_ENABLED kill switch).
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from app.broker.mt5 import BrokerError, MT5Client
from app.config import get_settings
from app.data.candles import CandleRepository
from app.data.decisions import StrategyDecisionRepository
from app.data.ingestion import IngestionService
from app.data.trades import TradeRepository
from app.db import Database
from app.execution.trader import REGIME_SHADOW_STRATEGY, Trader
from app.learning.registry import ModelRegistry
from app.learning.service import LearningService
from app.risk.kill_switch import KillSwitch
from app.risk.manager import RiskManager
from app.strategy.factory import build_strategy

settings = get_settings()

# Kill switch dynamique, persisté hors git (models/ est ignoré). Créé avant le
# lifespan pour que les endpoints /risk/* fonctionnent même sans DB/broker.
kill_switch = KillSwitch(
    Path(__file__).resolve().parents[1] / "models" / "kill_switch.json"
)


class ResolveTradeRequest(BaseModel):
    status: Literal["CANCELLED", "CLOSED"]
    exit_price: float | None = None
    closed_at: datetime | None = None

broker: MT5Client | None = None
database: Database | None = None
ingestion: IngestionService | None = None
trader: Trader | None = None
decisions_repo: StrategyDecisionRepository | None = None
learning: LearningService | None = None
_ingestion_task: asyncio.Task | None = None
_trade_task: asyncio.Task | None = None
_profit_task: asyncio.Task | None = None
_learning_task: asyncio.Task | None = None


def _broker_ready() -> bool:
    if settings.mt5_attach:
        return True
    return bool(
        settings.mt5_login.strip()
        and settings.mt5_password
        and settings.mt5_server
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global broker, database, ingestion, trader, decisions_repo, learning
    global _ingestion_task, _trade_task, _profit_task, _learning_task

    broker = MT5Client(settings)
    database = Database(settings)
    await database.connect()

    if database.is_connected:
        ingestion = IngestionService(settings, broker, CandleRepository(database.pool))
        decisions_repo = StrategyDecisionRepository(database.pool)
        trader = Trader(
            settings,
            broker,
            build_strategy(settings),
            RiskManager(settings, kill_switch),
            decisions_repo,
            TradeRepository(database.pool, settings.symbol),
        )
        learning = LearningService(settings, trader)
        if _broker_ready():
            if settings.ingest_enabled:
                _ingestion_task = asyncio.create_task(ingestion.run_loop())
            if settings.trading_loop_enabled:
                _trade_task = asyncio.create_task(trader.run_loop())
                # Moniteur rapide de prise de profit (mode scalp) : ne fait
                # rien si la stratégie active n'a pas close_on_profit=True.
                _profit_task = asyncio.create_task(trader.run_profit_monitor_loop())
        if settings.learning_enabled:
            _learning_task = asyncio.create_task(learning.run_loop())

    yield

    for task in (_ingestion_task, _trade_task, _profit_task, _learning_task):
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
    if not _broker_ready():
        raise HTTPException(
            status_code=503,
            detail=(
                "MetaTrader 5 non configuré : renseignez MT5_LOGIN, "
                "MT5_PASSWORD et MT5_SERVER (compte démo)"
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
        "symbol": settings.symbol,
        "broker_env": settings.broker_env,
        "trading_enabled": settings.trading_enabled,
        "broker_configured": _broker_ready(),
        "database_connected": database.is_connected if database else False,
        "ingestion_running": _ingestion_task is not None and not _ingestion_task.done(),
    }


@app.get("/market/price")
async def market_price() -> dict:
    ensure_broker_configured()
    try:
        return await broker.get_price()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/market/candles")
async def market_candles(granularity: str = "M1", count: int = 200) -> list[dict]:
    ensure_broker_configured()
    try:
        return await broker.get_candles(granularity=granularity, count=min(count, 1000))
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/account")
async def account() -> dict:
    ensure_broker_configured()
    try:
        return await broker.get_account_summary()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/positions")
async def positions() -> list[dict]:
    ensure_broker_configured()
    try:
        raw = await broker.get_open_positions()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    out = []
    for entry in raw:
        out.append(broker.normalise_position(entry))
    return out


# -- Data pipeline ----------------------------------------------------------


@app.post("/ingest/run")
async def ingest_run() -> dict:
    """Trigger one immediate refresh of the latest candles (all granularities)."""
    ensure_broker_configured()
    service = ensure_ingestion_ready()
    try:
        return {"upserted": await service.ingest_recent()}
    except BrokerError as exc:
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
    except BrokerError as exc:
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


@app.post("/candles/resample")
async def candles_resample(
    source: str = Query("M5"),
    target: str = Query("H1"),
    instrument: str | None = Query(None),
) -> dict:
    """Derive coarser candles (e.g. H1) from finer ones already stored."""
    service = ensure_ingestion_ready()
    try:
        return await service.resample(source, target, instrument)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/candles/stats")
async def candles_stats(instrument: str | None = Query(None)) -> dict:
    service = ensure_ingestion_ready()
    return {
        "instrument": instrument or settings.symbol,
        "granularities": await service.stats(instrument or settings.symbol),
    }


# -- Paper trading ----------------------------------------------------------


@app.post("/trade/step")
async def trade_step() -> dict:
    """Run one loop iteration: data -> signal -> risk -> (order if enabled)."""
    ensure_broker_configured()
    if trader is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    try:
        return await trader.step()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/trade/status")
async def trade_status() -> dict:
    strategy = trader._strategy if trader else None  # noqa: SLF001 — introspection
    return {
        "strategy": trader.strategy_name if trader else None,
        "paper_only": bool(trader and trader.strategy_paper_only),
        "trading_enabled": settings.trading_enabled,
        "loop_running": _trade_task is not None and not _trade_task.done(),
        "interval_seconds": settings.trade_interval_seconds,
        "close_on_profit": bool(getattr(strategy, "close_on_profit", False)),
        "profit_monitor_running": _profit_task is not None and not _profit_task.done(),
        "profit_check_interval_seconds": settings.profit_check_interval_seconds,
        "profit_close_min_net": float(
            getattr(strategy, "profit_close_min_net", settings.profit_close_min_net)
        ),
        "stop_loss_pct": (
            trader.effective_stop_loss_pct if trader else settings.stop_loss_pct
        ),
        "stop_loss_atr_multiplier": (
            trader.effective_stop_loss_atr_multiplier if trader else None
        ),
        "risk_reward_ratio": (
            trader.effective_risk_reward_ratio
            if trader
            else settings.risk_reward_ratio
        ),
    }


@app.get("/paper/validation")
async def paper_validation() -> dict:
    if trader is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    return await trader.paper_validation_status()


@app.get("/paper/regime-shadow")
async def paper_regime_shadow() -> dict:
    if decisions_repo is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    return await decisions_repo.shadow_regime_status(REGIME_SHADOW_STRATEGY)


@app.get("/paper/promotion-eligibility")
async def paper_promotion_eligibility() -> dict:
    if trader is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    return await trader.promotion_eligibility_status()


@app.get("/signal/latest")
async def signal_latest() -> dict:
    """Read-only structured signal preview for dashboards and diagnostics."""
    ensure_broker_configured()
    if trader is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    registry = ModelRegistry(
        Path(__file__).resolve().parents[1] / "models", settings.model_granularity
    )
    try:
        return await trader.preview_signal(model_version=registry.champion())
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/decisions/recent")
async def decisions_recent(limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    if decisions_repo is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    return await decisions_repo.recent(limit)


@app.get("/trades/reconciliation")
async def trades_reconciliation() -> dict:
    """Read-only comparison between DB open trades and broker positions."""
    ensure_broker_configured()
    if trader is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    try:
        return await trader.reconcile_open_trades(mutate=False)
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/trades/reconcile")
async def trades_reconcile(close_missing: bool = Query(False)) -> dict:
    """Backfill broker deal ids for matched open trades.

    With close_missing=true, DB trades missing from broker open positions are
    closed only when an accepted close activity is found in broker history.
    """
    ensure_broker_configured()
    if trader is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    try:
        return await trader.reconcile_open_trades(
            mutate=True, close_missing=close_missing
        )
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/trades/{trade_id}/resolve")
async def trades_resolve_manual(trade_id: str, payload: ResolveTradeRequest) -> dict:
    """Manual operator resolution for stale DB trades.

    CANCELLED marks the DB trade as cancelled. CLOSED requires `exit_price` and
    computes P&L from the stored entry, side and size.
    """
    if trader is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    result = await trader.resolve_trade_manual(
        trade_id,
        payload.status,
        payload.exit_price,
        payload.closed_at,
    )
    if not result.get("updated"):
        raise HTTPException(status_code=400, detail=result)
    return result


# -- Risk / kill switch -----------------------------------------------------


@app.get("/risk/status")
async def risk_status() -> dict:
    """État du moteur de risque : kill switch, limites configurées, stats jour."""
    stats = None
    if trader is not None:
        try:
            stats = await trader._trades.risk_stats()  # noqa: SLF001 — introspection read-only
        except Exception:  # noqa: BLE001 — le statut doit répondre même sans DB
            stats = None
    return {
        "kill_switch": kill_switch.status(),
        "trading_enabled": settings.trading_enabled,
        "limits": {
            "max_risk_per_trade_pct": settings.max_risk_per_trade_pct,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
            "max_weekly_loss_pct": settings.max_weekly_loss_pct,
            "max_open_positions": settings.max_open_positions,
            "max_consecutive_losses": settings.max_consecutive_losses,
            "cooldown_after_loss_minutes": settings.cooldown_after_loss_minutes,
            "cooldown_after_consecutive_losses_minutes": (
                settings.cooldown_after_consecutive_losses_minutes
            ),
        },
        "risk_stats": stats,
    }


@app.post("/risk/lock")
async def risk_lock(reason: str = Query("Verrouillage manuel opérateur")) -> dict:
    """Active le kill switch dynamique (aucun nouvel ordre d'ouverture)."""
    return kill_switch.lock(reason, source="operator")


@app.post("/risk/unlock")
async def risk_unlock(reason: str = Query(...)) -> dict:
    """Réactivation EXPLICITE du trading — une raison est obligatoire."""
    try:
        return kill_switch.unlock(reason, source="operator")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -- Learning loop ----------------------------------------------------------


@app.post("/learning/retrain")
async def learning_retrain(granularity: str | None = Query(None)) -> dict:
    """Run one retraining round: candidate configs compete, best is REGISTERED.

    Le vainqueur devient un CANDIDAT — jamais champion automatiquement.
    Promotion manuelle via POST /learning/promote. With ?granularity=H1,
    retrain on another granularity for measurement only.
    """
    if learning is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    if granularity and granularity != settings.model_granularity:
        from app.learning.trainer import retrain

        return await retrain(settings, granularity)
    return await learning.retrain_once()


@app.post("/learning/promote")
async def learning_promote(version: str = Query(...)) -> dict:
    """Promotion MANUELLE d'une version en champion (action opérateur).

    C'est le seul chemin de promotion : la boucle d'apprentissage n'y touche
    jamais. Le rechargement de stratégie reste soumis au verrou paper-only.
    """
    if learning is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    result = learning.promote(version)
    if not result.get("promoted"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/learning/adaptive")
async def learning_adaptive() -> dict:
    """État de l'auto-apprentissage de la stratégie scalp : paramètres actuels,
    statistiques de la fenêtre récente et derniers ajustements décidés seuls."""
    if trader is None:
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    return trader.adaptive_status()


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
