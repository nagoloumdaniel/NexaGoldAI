"""Paper-trading loop: data -> signal -> risk -> order.

Every iteration logs a StrategyDecision (executed or not). An order is only
sent when the RiskManager approves AND the kill switch (TRADING_ENABLED) is on
— so by default the engine accumulates an honest decision log on the demo
account without ever touching it.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.broker.capital import CapitalClient, CapitalError
from app.config import Settings
from app.data.decisions import StrategyDecisionRepository
from app.data.trades import TradeRepository
from app.risk.manager import RiskManager
from app.signals.structured import build_structured_signal
from app.strategy.base import Action, Strategy

logger = logging.getLogger("nexagold.trader")


def compute_bracket(
    action: Action, entry: float, stop_loss_pct: float, risk_reward: float
) -> tuple[float, float]:
    """Stop-loss and take-profit prices around the entry."""
    if action == Action.BUY:
        return entry * (1 - stop_loss_pct), entry * (1 + stop_loss_pct * risk_reward)
    return entry * (1 + stop_loss_pct), entry * (1 - stop_loss_pct * risk_reward)


def _extract_deal_id(confirmation: dict | None) -> str | None:
    """Best-effort extraction of the real dealId from a broker confirmation."""
    if not confirmation:
        return None
    affected = confirmation.get("affectedDeals") or []
    for deal in affected:
        deal_id = deal.get("dealId")
        if deal_id:
            return str(deal_id)
    return None


def _parse_broker_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _compute_pnl(side: str, units: float, entry: float, exit_price: float) -> float:
    if side == "BUY":
        return (exit_price - entry) * units
    return (entry - exit_price) * units


def _positive_signal_value(signal, key: str, fallback: float) -> float:
    try:
        value = float(signal.features.get(key, fallback))
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


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

    @property
    def strategy_paper_only(self) -> bool:
        return self._strategy.paper_only

    def set_strategy(self, strategy: Strategy) -> None:
        """Hot-swap the strategy (used by the learning loop on promotion)."""
        if self._strategy.paper_only and not strategy.paper_only:
            raise RuntimeError("A paper-only strategy cannot be hot-swapped automatically")
        self._strategy = strategy

    async def preview_signal(self, model_version: str | None = None) -> dict:
        """Read-only structured signal preview.

        This reuses the live strategy path, but never inserts a decision and
        never sends an order. It is safe for dashboards and diagnostics.
        """
        s = self._settings
        candles = await self._broker.get_candles(
            granularity=s.model_granularity, count=s.decision_candles
        )

        macro_candles = None
        if getattr(self._strategy, "needs_macro", False):
            try:
                macro_candles = await self._broker.get_candles(
                    epic=s.capital_macro_epic,
                    granularity=s.model_granularity,
                    count=s.decision_candles,
                )
            except CapitalError:
                macro_candles = []

        signal = self._strategy.evaluate(candles, macro_candles)
        price = None
        try:
            price = await self._broker.get_price()
        except CapitalError:
            price = None
        effective_version = getattr(self._strategy, "model_version", model_version)
        return build_structured_signal(
            s,
            self._strategy.name,
            signal,
            candles,
            price,
            effective_version,
        )

    async def step(self) -> dict:
        s = self._settings
        paper_reconciliation = None
        if self._strategy.paper_only and s.capital_env == "demo":
            try:
                paper_reconciliation = await self.reconcile_open_trades(
                    mutate=True, close_missing=True
                )
            except CapitalError as exc:
                logger.warning("Reconciliation paper differee: %s", exc)
        expired_closures = await self._close_expired_paper_positions()
        candles = await self._broker.get_candles(
            granularity=s.model_granularity, count=s.decision_candles
        )

        macro_candles = None
        if getattr(self._strategy, "needs_macro", False):
            try:
                macro_candles = await self._broker.get_candles(
                    epic=s.capital_macro_epic,
                    granularity=s.model_granularity,
                    count=s.decision_candles,
                )
            except CapitalError as exc:
                logger.warning("Macro (%s) indisponible: %s", s.capital_macro_epic, exc)
                macro_candles = []

        signal = self._strategy.evaluate(candles, macro_candles)
        decision_id = await self._decisions.insert(self._strategy.name, signal)

        out = {
            "decision_id": decision_id,
            "strategy": self._strategy.name,
            "action": signal.action.value,
            "confidence": round(signal.confidence, 3),
            "reason": signal.reason,
            "position_size": round(signal.position_size, 4),
            "status": "logged",
        }
        if expired_closures:
            out["expired_closures"] = expired_closures
        if paper_reconciliation is not None:
            out["paper_reconciliation"] = {
                "matched": paper_reconciliation["matched"],
                "closed": paper_reconciliation["closed"],
                "unresolved": len(paper_reconciliation["unresolved_closures"]),
            }

        if signal.action == Action.HOLD:
            out["status"] = "hold"
            return out
        if self._strategy.paper_only and s.capital_env != "demo":
            out["status"] = "paper_only_blocked"
            out["reason"] = "Strategie paper interdite hors environnement demo"
            return out

        price = await self._broker.get_price()
        if not price["tradeable"]:
            out["status"] = "market_closed"
            return out

        # Le broker impose une distance de stop minimale (plus large pour un
        # guaranteed stop). On élargit le stop si besoin AVANT le sizing, sinon
        # l'ordre est rejeté et/ou le risque réel ne correspond plus à la taille.
        rules = await self._broker.get_market_rules()
        use_guaranteed = s.use_guaranteed_stop and rules["guaranteed_stop_allowed"]
        min_stop_pct = (
            rules["min_guaranteed_stop_pct"] if use_guaranteed else rules["min_stop_pct"]
        )
        strategy_stop_pct = _positive_signal_value(
            signal, "stop_loss_pct", s.stop_loss_pct
        )
        risk_reward = _positive_signal_value(
            signal, "risk_reward_ratio", s.risk_reward_ratio
        )
        stop_pct = max(
            strategy_stop_pct,
            min_stop_pct * (1 + s.stop_distance_buffer),
        )
        out["stop_pct"] = round(stop_pct, 5)
        out["risk_reward_ratio"] = round(risk_reward, 3)
        out["guaranteed_stop"] = use_guaranteed

        account = await self._broker.get_account_summary()
        positions = await self._broker.get_open_positions()
        entry = price["ask"] if signal.action == Action.BUY else price["bid"]
        stop_loss, take_profit = compute_bracket(
            signal.action, entry, stop_pct, risk_reward
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
            guaranteed_stop=use_guaranteed,
            decimals=rules["decimal_places"],
        )
        deal_reference = order.get("dealReference")
        confirmation = None
        broker_trade_id = str(deal_reference) if deal_reference is not None else None
        if deal_reference is not None:
            try:
                confirmation = await self._broker.get_deal_confirmation(
                    str(deal_reference)
                )
                broker_trade_id = _extract_deal_id(confirmation) or broker_trade_id
            except CapitalError as exc:
                logger.warning("Confirmation broker indisponible: %s", exc)

        trade_id = await self._trades.insert_open(
            signal,
            decision.units,
            entry,
            stop_loss,
            take_profit,
            self._strategy.name,
            broker_trade_id,
        )
        await self._decisions.mark_executed(decision_id, trade_id)
        out["status"] = "executed"
        out["trade_id"] = trade_id
        out["order"] = order
        out["broker_trade_id"] = broker_trade_id
        if confirmation is not None:
            out["confirmation_status"] = confirmation.get("dealStatus")
        return out

    async def _close_expired_paper_positions(self) -> list[dict]:
        horizon_hours = self._strategy.paper_horizon_hours
        if (
            not self._strategy.paper_only
            or self._settings.capital_env != "demo"
            or not self._settings.trading_enabled
            or not horizon_hours
        ):
            return []

        now = datetime.now(timezone.utc)
        results = []
        for trade in await self._trades.open_trades():
            if trade.get("strategy") != self._strategy.name:
                continue
            opened_at = _parse_broker_time(trade.get("opened_at"))
            if opened_at is None or now - opened_at < timedelta(hours=horizon_hours):
                continue
            deal_id = await self._resolve_deal_id(trade.get("broker_trade_id"))
            if not deal_id:
                results.append(
                    {"trade_id": trade["id"], "status": "missing_deal_id"}
                )
                continue
            try:
                close_order = await self._broker.close_position_by_deal_id(deal_id)
                close_reference = close_order.get("dealReference")
                confirmation = (
                    await self._broker.get_deal_confirmation(str(close_reference))
                    if close_reference
                    else None
                )
            except CapitalError as exc:
                logger.warning("Cloture horizon echouee pour %s: %s", deal_id, exc)
                results.append(
                    {"trade_id": trade["id"], "status": "broker_error"}
                )
                continue

            exit_price = (confirmation or {}).get("level")
            closed_at = _parse_broker_time(
                (confirmation or {}).get("date")
                or (confirmation or {}).get("dateUTC")
            )
            if exit_price is not None and closed_at is not None:
                pnl = _compute_pnl(
                    trade["side"],
                    trade["units"],
                    trade["entry_price"],
                    float(exit_price),
                )
                await self._trades.close_trade(
                    trade["id"], float(exit_price), pnl, closed_at
                )
                results.append(
                    {
                        "trade_id": trade["id"],
                        "status": "closed_at_horizon",
                        "exit_price": float(exit_price),
                        "pnl": round(pnl, 2),
                    }
                )
            else:
                results.append(
                    {
                        "trade_id": trade["id"],
                        "status": "close_requested_pending_reconciliation",
                    }
                )
        return results

    async def paper_validation_status(self) -> dict:
        stats = await self._trades.paper_validation("expected-return-paper")
        target = self._settings.paper_validation_min_trades
        stats.update(
            {
                "target_closed_trades": target,
                "progress": min(stats["closed_trades"] / target, 1.0)
                if target > 0
                else 1.0,
                "eligible_for_review": stats["closed_trades"] >= target,
                "automatic_live_promotion": False,
            }
        )
        return stats

    async def reconcile_open_trades(
        self, mutate: bool = False, close_missing: bool = False
    ) -> dict:
        """Compare DB OPEN trades with broker open positions.

        `mutate=True` only backfills brokerTradeId when a reliable broker dealId
        is found. It deliberately does not close DB trades yet; realised P&L
        needs broker history/transactions, not a guessed last price.
        """
        broker_positions_raw = await self._broker.get_open_positions()
        broker_positions = [
            self._broker.normalise_position(p) for p in broker_positions_raw
        ]
        db_trades = await self._trades.open_trades()

        matched_position_ids: set[str] = set()
        rows = []
        updated = []
        closed = []
        unresolved_closures = []

        for trade in db_trades:
            match = self._match_position(trade, broker_positions, matched_position_ids)
            if match is None:
                close_event = None
                if close_missing and trade.get("broker_trade_id"):
                    close_event = await self._find_close_event(trade)
                if mutate and close_event is not None:
                    pnl = _compute_pnl(
                        trade["side"],
                        trade["units"],
                        trade["entry_price"],
                        close_event["exit_price"],
                    )
                    await self._trades.close_trade(
                        trade["id"],
                        close_event["exit_price"],
                        pnl,
                        close_event["closed_at"],
                    )
                    closed.append(
                        {
                            "trade_id": trade["id"],
                            "exit_price": close_event["exit_price"],
                            "pnl": round(pnl, 2),
                            "closed_at": close_event["closed_at"].isoformat(),
                            "source": close_event["source"],
                        }
                    )
                    rows.append(
                        {
                            "trade_id": trade["id"],
                            "broker_trade_id": trade["broker_trade_id"],
                            "side": trade["side"],
                            "units": trade["units"],
                            "status": "closed_from_broker",
                            "broker_pnl": round(pnl, 2),
                            "broker_open_level": None,
                        }
                    )
                    continue

                if close_missing and trade.get("broker_trade_id"):
                    unresolved_closures.append(
                        {
                            "trade_id": trade["id"],
                            "broker_trade_id": trade["broker_trade_id"],
                            "reason": "No accepted close activity found",
                        }
                    )
                rows.append(
                    {
                        "trade_id": trade["id"],
                        "broker_trade_id": trade["broker_trade_id"],
                        "side": trade["side"],
                        "units": trade["units"],
                        "status": "missing_on_broker",
                        "note": "Open in DB but no matching broker position",
                    }
                )
                continue

            broker_id = match.get("deal_id") or match.get("deal_reference")
            if broker_id:
                matched_position_ids.add(str(broker_id))
            if (
                mutate
                and broker_id
                and trade.get("broker_trade_id") != str(broker_id)
            ):
                await self._trades.set_broker_trade_id(trade["id"], str(broker_id))
                updated.append({"trade_id": trade["id"], "broker_trade_id": str(broker_id)})

            rows.append(
                {
                    "trade_id": trade["id"],
                    "broker_trade_id": trade["broker_trade_id"],
                    "broker_deal_id": match.get("deal_id"),
                    "side": trade["side"],
                    "units": trade["units"],
                    "status": "matched",
                    "broker_pnl": match.get("pnl"),
                    "broker_open_level": match.get("open_level"),
                }
            )

        untracked = [
            p
            for p in broker_positions
            if str(p.get("deal_id") or p.get("deal_reference")) not in matched_position_ids
        ]

        return {
            "mutated": mutate,
            "close_missing": close_missing,
            "db_open_trades": len(db_trades),
            "broker_open_positions": len(broker_positions),
            "matched": sum(1 for r in rows if r["status"] == "matched"),
            "closed": len(closed),
            "missing_on_broker": sum(
                1 for r in rows if r["status"] == "missing_on_broker"
            ),
            "untracked_broker_positions": len(untracked),
            "updated": updated,
            "closed_trades": closed,
            "unresolved_closures": unresolved_closures,
            "rows": rows,
            "untracked": untracked,
        }

    async def _find_close_event(self, trade: dict) -> dict | None:
        broker_id = await self._resolve_deal_id(trade.get("broker_trade_id"))
        if not broker_id:
            return None
        opened = _parse_broker_time(trade.get("opened_at")) or (
            datetime.now(timezone.utc) - timedelta(days=7)
        )
        end = datetime.now(timezone.utc)
        cursor = opened
        events = []
        # Capital.com caps activity date ranges to one day, so page by day.
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=1), end)
            try:
                events.extend(
                    await self._broker.get_activity_history(
                        cursor, chunk_end, deal_id=str(broker_id), detailed=True
                    )
                )
            except CapitalError as exc:
                logger.warning(
                    "Historique broker indisponible pour dealId=%s: %s",
                    broker_id,
                    exc,
                )
                return None
            cursor = chunk_end

        close_events = []
        for event in events:
            if event.get("dealId") != broker_id:
                continue
            if event.get("type") != "POSITION" or event.get("status") != "ACCEPTED":
                continue
            if event.get("source") not in {"CLOSE_OUT", "SL", "TP", "SYSTEM", "USER"}:
                continue
            details = event.get("details") or {}
            direction = details.get("direction")
            # Closing event direction should be opposite of the opened trade.
            if trade["side"] == "BUY" and direction != "SELL":
                continue
            if trade["side"] == "SELL" and direction != "BUY":
                continue
            level = details.get("level")
            closed_at = _parse_broker_time(event.get("dateUTC") or event.get("date"))
            if level is None or closed_at is None:
                continue
            close_events.append(
                {
                    "exit_price": float(level),
                    "closed_at": closed_at,
                    "source": event.get("source"),
                }
            )
        if not close_events:
            return None
        close_events.sort(key=lambda e: e["closed_at"], reverse=True)
        return close_events[0]

    async def _resolve_deal_id(self, broker_trade_id: str | None) -> str | None:
        """Resolve old stored dealReferences (`o_...`) to real dealIds if possible."""
        if not broker_trade_id:
            return None
        if not broker_trade_id.startswith(("o_", "p_")):
            return str(broker_trade_id)
        try:
            confirmation = await self._broker.get_deal_confirmation(broker_trade_id)
        except CapitalError as exc:
            logger.warning(
                "Impossible de convertir dealReference=%s en dealId: %s",
                broker_trade_id,
                exc,
            )
            return None
        return _extract_deal_id(confirmation)

    @staticmethod
    def _match_position(
        trade: dict, positions: list[dict], already_matched: set[str]
    ) -> dict | None:
        wanted_id = trade.get("broker_trade_id")
        side = trade.get("side")
        direction = "BUY" if side == "BUY" else "SELL"

        def position_key(position: dict) -> str:
            return str(position.get("deal_id") or position.get("deal_reference") or "")

        candidates = [p for p in positions if position_key(p) not in already_matched]

        if wanted_id:
            for position in candidates:
                ids = {position.get("deal_id"), position.get("deal_reference")}
                if str(wanted_id) in {str(i) for i in ids if i is not None}:
                    return position

        compatible = [
            p
            for p in candidates
            if p.get("instrument") == trade.get("instrument")
            and p.get("direction") == direction
            and abs(float(p.get("size") or 0) - float(trade.get("units") or 0)) < 0.01
        ]
        if len(compatible) == 1:
            return compatible[0]
        return None

    async def resolve_trade_manual(
        self,
        trade_id: str,
        status: str,
        exit_price: float | None = None,
        closed_at: datetime | None = None,
    ) -> dict:
        """Manual operator resolution for stale DB trades.

        Used when broker history cannot prove a closure. It only operates on
        currently OPEN DB trades and requires an explicit exit price for CLOSED.
        """
        trades = await self._trades.open_trades()
        trade = next((t for t in trades if t["id"] == trade_id), None)
        if trade is None:
            return {"updated": False, "reason": "Trade OPEN introuvable"}

        when = closed_at or datetime.now(timezone.utc)
        if status == "CANCELLED":
            await self._trades.cancel_trade(trade_id, when)
            return {
                "updated": True,
                "trade_id": trade_id,
                "status": "CANCELLED",
                "closed_at": when.isoformat(),
            }

        if status != "CLOSED":
            return {"updated": False, "reason": f"Statut non supporte: {status}"}
        if exit_price is None:
            return {
                "updated": False,
                "reason": "exit_price requis pour une cloture manuelle",
            }

        pnl = _compute_pnl(
            trade["side"],
            trade["units"],
            trade["entry_price"],
            exit_price,
        )
        await self._trades.close_trade(trade_id, exit_price, pnl, when)
        return {
            "updated": True,
            "trade_id": trade_id,
            "status": "CLOSED",
            "exit_price": exit_price,
            "pnl": round(pnl, 2),
            "closed_at": when.isoformat(),
        }

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
