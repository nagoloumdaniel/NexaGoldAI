"""Repository for Trade rows.

The engine records a Trade when it opens a position. Closing and P&L
reconciliation (polling the broker) is a later increment; for now this
captures entry, bracket and the deciding strategy/reason.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
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

    async def risk_stats(self) -> dict:
        """Statistiques consommées par le RiskManager (limites jour/semaine,
        série de pertes, cooldown). Basées sur les trades CLÔTURÉS du bot pour
        cet instrument — toutes stratégies confondues : changer de stratégie ne
        remet pas les limites à zéro.

        Convention temps : la DB stocke des timestamps naïfs UTC ; jour = depuis
        minuit UTC, semaine = depuis lundi 00:00 UTC.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT '
                'COALESCE(SUM("pnl") FILTER (WHERE "closedAt" >= $2), 0) AS today, '
                'COALESCE(SUM("pnl") FILTER (WHERE "closedAt" >= $3), 0) AS week '
                'FROM "Trade" WHERE "status" = \'CLOSED\'::"TradeStatus" '
                'AND "instrument" = $1 AND "pnl" IS NOT NULL',
                self._instrument,
                day_start,
                week_start,
            )
            recent = await conn.fetch(
                'SELECT "pnl", "closedAt" FROM "Trade" '
                'WHERE "status" = \'CLOSED\'::"TradeStatus" '
                'AND "instrument" = $1 AND "pnl" IS NOT NULL '
                'AND "closedAt" IS NOT NULL '
                'ORDER BY "closedAt" DESC LIMIT 30',
                self._instrument,
            )
        consecutive = 0
        for r in recent:
            if float(r["pnl"]) < 0:
                consecutive += 1
            else:
                break
        last_loss = next(
            (r["closedAt"] for r in recent if float(r["pnl"]) < 0), None
        )
        return {
            "realized_pnl_today": float(row["today"]),
            "realized_pnl_week": float(row["week"]),
            "consecutive_losses": consecutive,
            "last_loss_at": (
                last_loss.replace(tzinfo=timezone.utc).isoformat()
                if last_loss is not None
                else None
            ),
            "day_start": day_start.isoformat() + "Z",
            "week_start": week_start.isoformat() + "Z",
        }

    async def paper_validation(self, strategy: str) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT COUNT(*) AS total, '
                'COUNT(*) FILTER (WHERE "status" = \'OPEN\'::"TradeStatus") AS open, '
                'COUNT(*) FILTER (WHERE "status" = \'CLOSED\'::"TradeStatus") AS closed, '
                'COUNT(*) FILTER (WHERE "status" = \'CLOSED\'::"TradeStatus" '
                'AND "pnl" > 0) AS wins, '
                'COALESCE(SUM("pnl") FILTER (WHERE "status" = \'CLOSED\'::"TradeStatus"), 0) AS total_pnl, '
                'COALESCE(SUM("pnl") FILTER (WHERE "status" = \'CLOSED\'::"TradeStatus" '
                'AND "pnl" > 0), 0) AS gross_profit, '
                'COALESCE(SUM("pnl") FILTER (WHERE "status" = \'CLOSED\'::"TradeStatus" '
                'AND "pnl" < 0), 0) AS gross_loss, '
                'MIN("openedAt") AS started_at, MAX("closedAt") AS last_closed_at '
                'FROM "Trade" WHERE "strategy" = $1',
                strategy,
            )
        closed = int(row["closed"])
        wins = int(row["wins"])
        gross_loss = float(row["gross_loss"])
        gross_profit = float(row["gross_profit"])
        return {
            "strategy": strategy,
            "total_trades": int(row["total"]),
            "open_trades": int(row["open"]),
            "closed_trades": closed,
            "wins": wins,
            "losses": closed - wins,
            "win_rate": wins / closed if closed else 0.0,
            "total_pnl": float(row["total_pnl"]),
            "profit_factor": gross_profit / abs(gross_loss) if gross_loss < 0 else None,
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "last_closed_at": row["last_closed_at"].isoformat()
            if row["last_closed_at"]
            else None,
        }
