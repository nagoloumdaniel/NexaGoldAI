"""Repository for Trade rows.

The engine records a Trade when it opens a position. Closing and P&L
reconciliation (polling the broker) is a later increment; for now this
captures entry, bracket and the deciding strategy/reason.
"""

import json
import uuid
from decimal import Decimal

import asyncpg

from app.strategy.base import Signal


class TradeRepository:
    def __init__(self, pool: asyncpg.Pool, instrument: str):
        self._pool = pool
        self._instrument = instrument

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
