"""Analyse post-trade : MFE/MAE, résultat en R, durée — persistés en base.

Après chaque clôture, le Trader appelle `record()` qui :
1. relit le trade clos (entrée, sortie, stop, P&L) ;
2. récupère les bougies M1 couvrant la vie du trade ;
3. calcule l'excursion favorable/défavorable maximale en R (risque = distance
   entrée→stop) et le résultat en R ;
4. insère une ligne `TradeResult`.

C'est la matière première des futurs modèles de qualité de signal (labels) et
du classificateur d'erreurs. L'analyse ne doit JAMAIS casser l'exécution : tout
échec est journalisé puis avalé par l'appelant.
"""

import json
import logging
import uuid
from decimal import Decimal

import asyncpg

from app.analysis.classification import classify_trade

logger = logging.getLogger("nexagold.posttrade")


def compute_excursions(
    candles: list[dict], side: str, entry_price: float, risk_per_unit: float
) -> tuple[float | None, float | None]:
    """MFE/MAE en R sur la vie du trade (bougies M1 entrée→sortie incluses).

    MFE >= 0 (meilleure excursion dans le sens du trade), MAE <= 0 (pire
    excursion contre le trade). None si le risque unitaire est inconnu.
    """
    if risk_per_unit <= 0 or not candles:
        return None, None
    mfe = 0.0
    mae = 0.0
    for c in candles:
        if side == "BUY":
            mfe = max(mfe, (float(c["high"]) - entry_price) / risk_per_unit)
            mae = min(mae, (float(c["low"]) - entry_price) / risk_per_unit)
        else:
            mfe = max(mfe, (entry_price - float(c["low"])) / risk_per_unit)
            mae = min(mae, (entry_price - float(c["high"])) / risk_per_unit)
    return round(mfe, 4), round(mae, 4)


class PostTradeAnalyzer:
    def __init__(self, pool: asyncpg.Pool, instrument: str):
        self._pool = pool
        self._instrument = instrument

    async def record(self, trade_id: str, exit_source: str | None = None) -> dict:
        """Analyse un trade CLÔTURÉ et persiste le TradeResult (idempotent)."""
        async with self._pool.acquire() as conn:
            trade = await conn.fetchrow(
                'SELECT "id", "side", "units", "entryPrice", "exitPrice", '
                '"stopLoss", "pnl", "strategy", "openedAt", "closedAt", '
                '"features" '
                'FROM "Trade" WHERE "id" = $1 '
                'AND "status" = \'CLOSED\'::"TradeStatus"',
                trade_id,
            )
            if trade is None:
                return {"recorded": False, "reason": "Trade clos introuvable"}
            if trade["exitPrice"] is None or trade["closedAt"] is None:
                return {"recorded": False, "reason": "Clôture incomplète"}

            entry = float(trade["entryPrice"])
            exit_price = float(trade["exitPrice"])
            stop = float(trade["stopLoss"]) if trade["stopLoss"] is not None else None
            side = str(trade["side"])
            risk = abs(entry - stop) if stop is not None else 0.0

            candles = await conn.fetch(
                'SELECT "high", "low" FROM "Candle" '
                "WHERE \"instrument\" = $1 AND \"granularity\" = 'M1' "
                'AND "time" >= $2 AND "time" <= $3 ORDER BY "time"',
                self._instrument,
                trade["openedAt"],
                trade["closedAt"],
            )
            mfe_r, mae_r = compute_excursions(
                [dict(c) for c in candles], side, entry, risk
            )
            signed = exit_price - entry if side == "BUY" else entry - exit_price
            result_r = round(signed / risk, 4) if risk > 0 else None
            holding = int((trade["closedAt"] - trade["openedAt"]).total_seconds())

            features = trade["features"]
            if isinstance(features, str):
                try:
                    features = json.loads(features)
                except ValueError:
                    features = None
            rr = None
            if isinstance(features, dict):
                try:
                    rr = float(features.get("risk_reward_ratio") or 0) or None
                except (TypeError, ValueError):
                    rr = None
            verdict = classify_trade(result_r, mfe_r, mae_r, rr, exit_source)

            await conn.execute(
                'INSERT INTO "TradeResult" '
                '("id", "tradeId", "strategy", "side", "entryTime", "exitTime", '
                '"entryPrice", "exitPrice", "pnl", "resultR", "mfeR", "maeR", '
                '"holdingSeconds", "exitSource", "classification", '
                '"errorCategory", "details") '
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, "
                "$13, $14, $15, $16, $17::jsonb) "
                'ON CONFLICT ("tradeId") DO UPDATE SET '
                '"exitSource" = COALESCE(EXCLUDED."exitSource", "TradeResult"."exitSource"), '
                '"mfeR" = COALESCE(EXCLUDED."mfeR", "TradeResult"."mfeR"), '
                '"maeR" = COALESCE(EXCLUDED."maeR", "TradeResult"."maeR"), '
                '"classification" = EXCLUDED."classification", '
                '"errorCategory" = EXCLUDED."errorCategory", '
                '"details" = EXCLUDED."details"',
                "tr_" + uuid.uuid4().hex,
                trade["id"],
                trade["strategy"],
                side,
                trade["openedAt"],
                trade["closedAt"],
                Decimal(str(round(entry, 3))),
                Decimal(str(round(exit_price, 3))),
                trade["pnl"] if trade["pnl"] is not None else Decimal("0"),
                Decimal(str(result_r)) if result_r is not None else None,
                Decimal(str(mfe_r)) if mfe_r is not None else None,
                Decimal(str(mae_r)) if mae_r is not None else None,
                holding,
                exit_source,
                verdict.classification,
                verdict.error_category,
                json.dumps(
                    {
                        "m1_bars": len(candles),
                        "risk_per_unit": risk,
                        "risk_reward": rr,
                        "explanation": verdict.explanation,
                    }
                ),
            )
        return {
            "recorded": True,
            "trade_id": trade_id,
            "result_r": result_r,
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "holding_seconds": holding,
            "exit_source": exit_source,
            "classification": verdict.classification,
            "error_category": verdict.error_category,
            "explanation": verdict.explanation,
        }

    async def recent(self, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT "tradeId", "strategy", "side", "entryTime", "exitTime", '
                '"entryPrice", "exitPrice", "pnl", "resultR", "mfeR", "maeR", '
                '"holdingSeconds", "exitSource", "classification", '
                '"errorCategory", "details" '
                'FROM "TradeResult" ORDER BY "exitTime" DESC LIMIT $1',
                limit,
            )
        return [
            {
                "trade_id": r["tradeId"],
                "strategy": r["strategy"],
                "side": r["side"],
                "entry_time": r["entryTime"].isoformat(),
                "exit_time": r["exitTime"].isoformat(),
                "entry_price": float(r["entryPrice"]),
                "exit_price": float(r["exitPrice"]),
                "pnl": float(r["pnl"]),
                "result_r": float(r["resultR"]) if r["resultR"] is not None else None,
                "mfe_r": float(r["mfeR"]) if r["mfeR"] is not None else None,
                "mae_r": float(r["maeR"]) if r["maeR"] is not None else None,
                "holding_seconds": r["holdingSeconds"],
                "exit_source": r["exitSource"],
                "classification": r["classification"],
                "error_category": r["errorCategory"],
            }
            for r in rows
        ]

    async def stats(self, strategy: str | None = None) -> dict:
        """Agrégats MFE/MAE/R — le tableau de bord du 'où meurent les trades'."""
        where = 'WHERE "strategy" = $1' if strategy else ""
        args = [strategy] if strategy else []
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f'SELECT COUNT(*) AS n, AVG("resultR") AS avg_r, '
                f'AVG("mfeR") AS avg_mfe, AVG("maeR") AS avg_mae, '
                f'COUNT(*) FILTER (WHERE "resultR" > 0) AS wins '
                f'FROM "TradeResult" {where}',
                *args,
            )
        n = int(row["n"])
        return {
            "strategy": strategy,
            "results": n,
            "wins": int(row["wins"]),
            "win_rate": round(int(row["wins"]) / n, 4) if n else None,
            "avg_result_r": float(row["avg_r"]) if row["avg_r"] is not None else None,
            "avg_mfe_r": float(row["avg_mfe"]) if row["avg_mfe"] is not None else None,
            "avg_mae_r": float(row["avg_mae"]) if row["avg_mae"] is not None else None,
        }


class JournalRepository:
    """RiskDecision + SystemEvent — journaux durables du moteur."""

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def record_risk_decision(
        self,
        decision_id: str | None,
        approved: bool,
        reason: str,
        units: float,
        risk_stats: dict | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO "RiskDecision" '
                '("id", "decisionId", "approved", "reason", "units", "riskStats") '
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
                "rd_" + uuid.uuid4().hex,
                decision_id,
                approved,
                reason,
                Decimal(str(round(units, 2))),
                json.dumps(risk_stats or {}, default=float),
            )

    async def record_event(
        self,
        event_type: str,
        severity: str,
        component: str,
        message: str,
        payload: dict | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO "SystemEvent" '
                '("id", "eventType", "severity", "component", "message", "payload") '
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
                "se_" + uuid.uuid4().hex,
                event_type,
                severity,
                component,
                message,
                json.dumps(payload or {}, default=float),
            )

    async def recent_risk_decisions(self, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT "time", "decisionId", "approved", "reason", "units" '
                'FROM "RiskDecision" ORDER BY "time" DESC LIMIT $1',
                limit,
            )
        return [
            {
                "time": r["time"].isoformat(),
                "decision_id": r["decisionId"],
                "approved": r["approved"],
                "reason": r["reason"],
                "units": float(r["units"]) if r["units"] is not None else None,
            }
            for r in rows
        ]

    async def recent_events(self, limit: int = 50) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT "time", "eventType", "severity", "component", "message" '
                'FROM "SystemEvent" ORDER BY "time" DESC LIMIT $1',
                limit,
            )
        return [
            {
                "time": r["time"].isoformat(),
                "event_type": r["eventType"],
                "severity": r["severity"],
                "component": r["component"],
                "message": r["message"],
            }
            for r in rows
        ]

