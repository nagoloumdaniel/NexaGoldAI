"""Paper-trading loop: data -> signal -> risk -> order.

Every iteration logs a StrategyDecision (executed or not). An order is only
sent when the RiskManager approves AND the kill switch (TRADING_ENABLED) is on
— so by default the engine accumulates an honest decision log on the demo
account without ever touching it.
"""

import asyncio
import logging

from app.broker.capital import CapitalClient, CapitalError
from app.config import Settings
from app.data.decisions import StrategyDecisionRepository
from app.data.trades import TradeRepository
from app.risk.manager import RiskManager
from app.strategy.base import Action, Strategy

logger = logging.getLogger("nexagold.trader")


def compute_bracket(
    action: Action, entry: float, stop_loss_pct: float, risk_reward: float
) -> tuple[float, float]:
    """Stop-loss and take-profit prices around the entry."""
    if action == Action.BUY:
        return entry * (1 - stop_loss_pct), entry * (1 + stop_loss_pct * risk_reward)
    return entry * (1 + stop_loss_pct), entry * (1 - stop_loss_pct * risk_reward)


class Trader:
    def __init__(
        self,
        settings: Settings,
        broker: CapitalClient,
        strategy: Strategy,
        risk: RiskManager,
        decisions: StrategyDecisionRepository,
        trades: TradeRepository,
    ):
        self._settings = settings
        self._broker = broker
        self._strategy = strategy
        self._risk = risk
        self._decisions = decisions
        self._trades = trades

    @property
    def strategy_name(self) -> str:
        return self._strategy.name

    async def step(self) -> dict:
        s = self._settings
        candles = await self._broker.get_candles(
            granularity=s.model_granularity, count=s.decision_candles
        )
        signal = self._strategy.evaluate(candles)
        decision_id = await self._decisions.insert(self._strategy.name, signal)

        out = {
            "decision_id": decision_id,
            "strategy": self._strategy.name,
            "action": signal.action.value,
            "confidence": round(signal.confidence, 3),
            "reason": signal.reason,
            "status": "logged",
        }

        if signal.action == Action.HOLD:
            out["status"] = "hold"
            return out

        price = await self._broker.get_price()
        if not price["tradeable"]:
            out["status"] = "market_closed"
            return out

        account = await self._broker.get_account_summary()
        positions = await self._broker.get_open_positions()
        entry = price["ask"] if signal.action == Action.BUY else price["bid"]
        stop_loss, take_profit = compute_bracket(
            signal.action, entry, s.stop_loss_pct, s.risk_reward_ratio
        )

        decision = self._risk.review(signal, account, positions, entry, stop_loss)
        out["risk"] = {
            "approved": decision.approved,
            "reason": decision.reason,
            "units": decision.units,
        }
        if not decision.approved:
            out["status"] = "rejected"
            return out

        order = await self._broker.create_market_order(
            units=decision.units,
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
        )
        trade_id = await self._trades.insert_open(
            signal,
            decision.units,
            entry,
            stop_loss,
            take_profit,
            self._strategy.name,
            order.get("dealReference"),
        )
        await self._decisions.mark_executed(decision_id, trade_id)
        out["status"] = "executed"
        out["trade_id"] = trade_id
        out["order"] = order
        return out

    async def run_loop(self) -> None:
        interval = self._settings.trade_interval_seconds
        logger.info(
            "Boucle de trading démarrée (stratégie=%s, intervalle=%ss, ordres=%s)",
            self._strategy.name,
            interval,
            "ON" if self._settings.trading_enabled else "OFF (kill switch)",
        )
        while True:
            try:
                result = await self.step()
                logger.info("Trade step: %s", result.get("status"))
            except CapitalError as exc:
                logger.warning("Trade step ignoré (broker): %s", exc)
            except Exception:  # noqa: BLE001 — the loop must never die silently
                logger.exception("Erreur inattendue dans la boucle de trading")
            await asyncio.sleep(interval)
