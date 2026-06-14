"""Repository for StrategyDecision rows.

Every signal the engine produces is logged here — executed or not — so the
dashboard can show "Raisons de la décision IA" and the data feeds retraining.
"""

import json
import uuid
from decimal import Decimal

import asyncpg

from app.strategy.base import Signal


class StrategyDecisionRepository:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def insert(self, strategy: str, signal: Signal) -> str:
        decision_id = "sd_" + uuid.uuid4().hex
        async with self._pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO "StrategyDecision" '
                '("id", "strategy", "action", "confidence", "reason", "features", "executed") '
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb, false)",
                decision_id,
                strategy,
                signal.action.value,
                Decimal(str(round(signal.confidence, 3))),
                signal.reason,
                json.dumps(signal.features, default=float),
            )
        return decision_id

    async def mark_executed(self, decision_id: str, trade_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                'UPDATE "StrategyDecision" SET "executed" = true, "tradeId" = $2 WHERE "id" = $1',
                decision_id,
                trade_id,
            )

    async def recent(self, limit: int = 20) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT "time", "strategy", "action", "confidence", "reason", "executed" '
                'FROM "StrategyDecision" ORDER BY "time" DESC LIMIT $1',
                limit,
            )
        return [
            {
                "time": r["time"].isoformat(),
                "strategy": r["strategy"],
                "action": r["action"],
                "confidence": float(r["confidence"]),
                "reason": r["reason"],
                "executed": r["executed"],
            }
            for r in rows
        ]
