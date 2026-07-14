"""Repository for Trade rows.

The engine records a Trade when it opens a position. Closing and P&L
reconciliation (polling the broker) is a later increment; for now this
captures entry, bracket and the deciding strategy/reason.
"""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import asyncpg

from app.strategy.base import Signal


class TradeRepository:
    def __init__(self, pool: asyncpg.Pool, instrument: str):
        self._pool = pool
        self._instrument = instrument

    async def open_trades(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT "id", "instrument", "side", "units", "entryPrice", '
                '"stopLoss", "takeProfit", "strategy", "brokerTradeId", "openedAt" '
                'FROM "Trade" WHERE "status" = \'OPEN\'::"TradeStatus" '
                'ORDER BY "openedAt" DESC'
            )
        return [
            {
                "id": r["id"],
                "instrument": r["instrument"],
                "side": r["side"],
                "units": float(r["units"]),
                "entry_price": float(r["entryPrice"]),
                "stop_loss": float(r["stopLoss"]) if r["stopLoss"] is not None else None,
                "take_profit": float(r["takeProfit"])
                if r["takeProfit"] is not None
                else None,
                "strategy": r["strategy"],
                "broker_trade_id": r["brokerTradeId"],
                "opened_at": r["openedAt"].isoformat(),
            }
            for r in rows
        ]

    async def set_broker_trade_id(self, trade_id: str, broker_trade_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                'UPDATE "Trade" SET "brokerTradeId" = $2 WHERE "id" = $1',
                trade_id,
                broker_trade_id,
            )

    async def close_trade(
        self, trade_id: str, exit_price: float, pnl: float, closed_at: datetime
    ) -> None:
        if closed_at.tzinfo is not None:
            closed_at = closed_at.astimezone(timezone.utc).replace(tzinfo=None)
        async with self._pool.acquire() as conn:
            await conn.execute(
                'UPDATE "Trade" SET "status" = \'CLOSED\'::"TradeStatus", '
                '"exitPrice" = $2, "pnl" = $3, "closedAt" = $4 WHERE "id" = $1',
                trade_id,
                Decimal(str(round(exit_price, 3))),
                Decimal(str(round(pnl, 2))),
                closed_at,
            )

    async def cancel_trade(self, trade_id: str, closed_at: datetime) -> None:
        if closed_at.tzinfo is not None:
            closed_at = closed_at.astimezone(timezone.utc).replace(tzinfo=None)
        async with self._pool.acquire() as conn:
            await conn.execute(
                'UPDATE "Trade" SET "status" = \'CANCELLED\'::"TradeStatus", '
                '"closedAt" = $2 WHERE "id" = $1',
                trade_id,
                closed_at,
            )

    async def insert_open(
        self,
        signal: Signal,
        units: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        strategy: str,
        broker_ref: str | None,
    ) -> str:
        trade_id = "tr_" + uuid.uuid4().hex
        side = "BUY" if units > 0 else "SELL"
        async with self._pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO "Trade" '
                '("id", "instrument", "side", "units", "entryPrice", "stopLoss", '
                '"takeProfit", "status", "strategy", "reason", "features", "brokerTradeId") '
                'VALUES ($1, $2, $3::"TradeSide", $4, $5, $6, $7, '
                "'OPEN'::\"TradeStatus\", $8, $9, $10::jsonb, $11)",
                trade_id,
                self._instrument,
                side,
                Decimal(str(round(abs(units), 2))),
                Decimal(str(round(entry_price, 3))),
                Decimal(str(round(stop_loss, 3))),
                Decimal(str(round(take_profit, 3))),
                strategy,
                signal.reason,
                json.dumps(signal.features, default=float),
                str(broker_ref) if broker_ref is not None else None,
            )
        return trade_id
