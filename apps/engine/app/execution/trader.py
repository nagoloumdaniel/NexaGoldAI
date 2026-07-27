"""Paper-trading loop: data -> signal -> risk -> order.

Every iteration logs a StrategyDecision (executed or not). An order is only
sent when the RiskManager approves AND the kill switch (TRADING_ENABLED) is on
— so by default the engine accumulates an honest decision log on the demo
account without ever touching it.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.analysis.post_trade import JournalRepository, PostTradeAnalyzer
from app.broker.mt5 import MAGIC, BrokerError, MT5Client
from app.config import Settings
from app.data.decisions import StrategyDecisionRepository
from app.data.trades import TradeRepository
from app.fundamental.calendar import NewsFilter
from app.risk.manager import RiskManager
from app.signals.math_features import build_math_summary
from app.signals.regime import classify_regime
from app.signals.structured import build_structured_signal
from app.strategy.base import Action, Signal, Strategy

logger = logging.getLogger("nexagold.trader")

REGIME_SHADOW_STRATEGY = "expected-return-paper-regime-shadow"
REGIME_SHADOW_FILTER = "exclude_regime:BULLISH_TREND"


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


def _regime_shadow_signal(
    settings: Settings,
    candles: list[dict],
    signal: Signal,
    decision_id: str,
) -> Signal | None:
    """Prospective candidate filter, logged only as a non-executable decision."""
    if signal.features.get("signal_kind") != "expected_return":
        return None

    math_summary = build_math_summary(
        candles,
        min_count=min(settings.decision_candles, 50),
    )
    regime_inputs = {
        **math_summary,
        "data_quality_score": float(math_summary.get("data_quality_score") or 0.0),
    }
    regime = classify_regime(regime_inputs)
    blocked = signal.action == Action.BUY and regime["regime"] == "BULLISH_TREND"
    features = {
        **signal.features,
        "signal_kind": "expected_return_regime_shadow",
        "shadow_of_decision_id": decision_id,
        "shadow_filter": REGIME_SHADOW_FILTER,
        "shadow_filtered": blocked,
        "shadow_execution_allowed": False,
        "base_action": signal.action.value,
        "market_regime": regime["regime"],
        "regime_trend": regime["trend"],
        "regime_volatility": regime["volatility"],
        "regime_confidence": regime["confidence"],
        "regime_filter_candidate": True,
        "paper_only": True,
    }
    if blocked:
        return Signal(
            Action.HOLD,
            signal.confidence,
            (
                f"Shadow {REGIME_SHADOW_FILTER}: BUY bloqué en "
                f"{regime['regime']}"
            ),
            features,
            0.0,
        )
    return Signal(
        signal.action,
        signal.confidence,
        f"Shadow {REGIME_SHADOW_FILTER}: décision conservée",
        features,
        signal.position_size,
    )


class Trader:
    def __init__(
        self,
        settings: Settings,
        broker: MT5Client,
        strategy: Strategy,
        risk: RiskManager,
        decisions: StrategyDecisionRepository,
        trades: TradeRepository,
        news: NewsFilter | None = None,
        post_trade: PostTradeAnalyzer | None = None,
        journal: JournalRepository | None = None,
    ):
        self._settings = settings
        self._broker = broker
        self._strategy = strategy
        self._risk = risk
        self._decisions = decisions
        self._trades = trades
        self._news = news
        self._post_trade = post_trade
        self._journal = journal

    async def _analyze_closed_trade(self, trade_id: str, source: str) -> None:
        """Analyse post-trade (MFE/MAE, R) — ne casse jamais l'exécution."""
        if self._post_trade is None:
            return
        try:
            result = await self._post_trade.record(trade_id, exit_source=source)
            if result.get("recorded"):
                logger.info(
                    "Post-trade %s: R=%s MFE=%s MAE=%s (%s)",
                    trade_id,
                    result.get("result_r"),
                    result.get("mfe_r"),
                    result.get("mae_r"),
                    source,
                )
        except Exception:  # noqa: BLE001 — l'analyse ne bloque jamais le trading
            logger.exception("Analyse post-trade échouée pour %s", trade_id)

    async def _log_risk_decision(
        self, decision_id: str, decision, risk_stats: dict | None
    ) -> None:
        if self._journal is None:
            return
        try:
            await self._journal.record_risk_decision(
                decision_id,
                decision.approved,
                decision.reason,
                decision.units,
                risk_stats,
            )
        except Exception:  # noqa: BLE001 — le journal ne bloque jamais le trading
            logger.exception("Journalisation de la décision de risque échouée")

    @property
    def strategy_name(self) -> str:
        return self._strategy.name

    @property
    def strategy_paper_only(self) -> bool:
        return self._strategy.paper_only

    @property
    def effective_stop_loss_pct(self) -> float:
        return float(
            getattr(self._strategy, "stop_loss_floor_pct", self._settings.stop_loss_pct)
        )

    @property
    def effective_stop_loss_atr_multiplier(self) -> float | None:
        value = getattr(self._strategy, "stop_loss_atr_multiplier", None)
        return float(value) if value is not None else None

    @property
    def effective_risk_reward_ratio(self) -> float:
        return float(
            getattr(
                self._strategy,
                "risk_reward_ratio",
                self._settings.risk_reward_ratio,
            )
        )

    def set_strategy(self, strategy: Strategy) -> None:
        """Hot-swap the strategy (used by the learning loop on promotion)."""
        if self._strategy.paper_only and not strategy.paper_only:
            raise RuntimeError("A paper-only strategy cannot be hot-swapped automatically")
        self._strategy = strategy

    async def _bot_positions(self) -> list[dict]:
        """Positions ouvertes appartenant au bot (symbole + magic) uniquement."""
        return await self._broker.get_open_positions(
            symbol=self._settings.symbol, magic=MAGIC
        )

    async def _fetch_extra_candles(self) -> dict[str, list[dict]] | None:
        """Bougies des timeframes d'analyse déclarés par la stratégie."""
        grans = getattr(self._strategy, "extra_granularities", ()) or ()
        if not grans:
            return None
        extra: dict[str, list[dict]] = {}
        for gran in grans:
            extra[gran] = await self._broker.get_candles(
                granularity=gran, count=self._settings.decision_candles
            )
        return extra

    def _evaluate(
        self,
        candles: list[dict],
        macro_candles: list[dict] | None,
        extra: dict[str, list[dict]] | None,
    ) -> Signal:
        if extra is not None:
            return self._strategy.evaluate(candles, macro_candles, extra=extra)
        return self._strategy.evaluate(candles, macro_candles)

    def _notify_tuner(self, pnl: float, side: str, source: str) -> None:
        """Alimente l'apprentissage adaptatif avec chaque trade clôturé."""
        tuner = getattr(self._strategy, "tuner", None)
        if tuner is None:
            return
        try:
            tuner.record_trade(pnl=pnl, side=side, source=source)
        except Exception:  # noqa: BLE001 — l'apprentissage ne doit jamais casser l'exécution
            logger.exception("Échec de l'enregistrement du trade dans le tuner")

    def adaptive_status(self) -> dict:
        tuner = getattr(self._strategy, "tuner", None)
        if tuner is None:
            return {
                "enabled": False,
                "reason": (
                    f"La stratégie {self._strategy.name} n'a pas de tuner adaptatif"
                ),
            }
        return tuner.status()

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
                    symbol=s.mt5_macro_symbol,
                    granularity=s.model_granularity,
                    count=s.decision_candles,
                )
            except BrokerError:
                macro_candles = []

        try:
            extra = await self._fetch_extra_candles()
        except BrokerError:
            extra = None
        signal = self._evaluate(candles, macro_candles, extra)
        price = None
        try:
            price = await self._broker.get_price()
        except BrokerError:
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
        if self._strategy.paper_only and s.broker_env == "demo":
            try:
                paper_reconciliation = await self.reconcile_open_trades(
                    mutate=True, close_missing=True
                )
            except BrokerError as exc:
                logger.warning("Reconciliation paper differee: %s", exc)
        expired_closures = await self._close_expired_paper_positions()
        # Filet de sécurité : même si le moniteur rapide est arrêté, aucune
        # position gagnante ne doit attendre le prochain signal pour sortir.
        profit_closures = []
        try:
            profit_closures = await self.close_profitable_positions()
        except BrokerError as exc:
            logger.warning("Prise de profit différée: %s", exc)
        candles = await self._broker.get_candles(
            granularity=s.model_granularity, count=s.decision_candles
        )

        macro_candles = None
        if getattr(self._strategy, "needs_macro", False):
            try:
                macro_candles = await self._broker.get_candles(
                    symbol=s.mt5_macro_symbol,
                    granularity=s.model_granularity,
                    count=s.decision_candles,
                )
            except BrokerError as exc:
                logger.warning("Macro (%s) indisponible: %s", s.mt5_macro_symbol, exc)
                macro_candles = []

        extra = await self._fetch_extra_candles()
        signal = self._evaluate(candles, macro_candles, extra)
        decision_id = await self._decisions.insert(self._strategy.name, signal)
        shadow_signal = _regime_shadow_signal(s, candles, signal, decision_id)
        shadow_decision_id = None
        if shadow_signal is not None:
            shadow_decision_id = await self._decisions.insert(
                REGIME_SHADOW_STRATEGY,
                shadow_signal,
            )

        out = {
            "decision_id": decision_id,
            "strategy": self._strategy.name,
            "action": signal.action.value,
            "confidence": round(signal.confidence, 3),
            "reason": signal.reason,
            "position_size": round(signal.position_size, 4),
            "status": "logged",
        }
        if shadow_decision_id is not None:
            out["shadow_decision_id"] = shadow_decision_id
            out["shadow_filter"] = REGIME_SHADOW_FILTER
        if expired_closures:
            out["expired_closures"] = expired_closures
        if profit_closures:
            out["profit_closures"] = profit_closures
        if paper_reconciliation is not None:
            out["paper_reconciliation"] = {
                "matched": paper_reconciliation["matched"],
                "closed": paper_reconciliation["closed"],
                "unresolved": len(paper_reconciliation["unresolved_closures"]),
            }

        if signal.action == Action.HOLD:
            out["status"] = "hold"
            return out
        if self._strategy.paper_only and s.broker_env != "demo":
            out["status"] = "paper_only_blocked"
            out["reason"] = "Stratégie paper interdite hors environnement démo"
            return out
        if (
            s.regime_filter_enforced
            and shadow_signal is not None
            and shadow_signal.features.get("shadow_filtered")
        ):
            out["status"] = "regime_blocked"
            out["reason"] = shadow_signal.reason
            return out

        # Filtre d'annonces économiques (fail-closed) : aucun nouvel ordre dans
        # les fenêtres d'annonces, ni quand le calendrier est indisponible.
        # Les clôtures ne passent jamais par ici — réduire le risque reste permis.
        if s.news_filter_enabled:
            if self._news is None:
                out["status"] = "news_blocked"
                out["reason"] = (
                    "Filtre d'annonces activé mais non initialisé — fail-closed"
                )
                return out
            verdict = await self._news.check()
            if verdict["blocked"]:
                out["status"] = "news_blocked"
                out["reason"] = verdict["reason"]
                if verdict.get("event"):
                    out["news_event"] = verdict["event"]
                return out

        price = await self._broker.get_price()
        if not price["tradeable"]:
            out["status"] = "market_closed"
            return out

        # Garde de spread : les spreads MT5 s'élargissent au rollover et sur
        # les annonces — exécuter à ces moments détruit l'espérance mesurée.
        mid = (price["bid"] + price["ask"]) / 2
        spread_pct = (price["ask"] - price["bid"]) / mid if mid > 0 else 0.0
        out["spread_pct"] = round(spread_pct, 6)
        if spread_pct > s.max_spread_pct:
            out["status"] = "spread_too_wide"
            out["reason"] = (
                f"Spread {spread_pct:.4%} > plafond {s.max_spread_pct:.4%}"
            )
            return out

        # Le broker impose une distance de stop minimale. On élargit le stop si
        # besoin AVANT le sizing, sinon l'ordre est rejeté et/ou le risque réel
        # ne correspond plus à la taille.
        rules = await self._broker.get_market_rules()
        min_stop_pct = rules["min_stop_pct"]
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

        account = await self._broker.get_account_summary()
        # Défense en profondeur : BROKER_ENV peut mentir, pas le terminal. Une
        # stratégie paper ne touche jamais un compte que MT5 déclare réel.
        if self._strategy.paper_only and account.get("is_demo") is not True:
            out["status"] = "paper_only_blocked"
            out["reason"] = "Le compte MT5 connecté n'est pas un compte démo"
            return out
        positions = await self._bot_positions()
        entry = price["ask"] if signal.action == Action.BUY else price["bid"]
        stop_loss, take_profit = compute_bracket(
            signal.action, entry, stop_pct, risk_reward
        )

        # Statistiques de risque depuis la DB (pertes réalisées jour/semaine,
        # série de pertes) : indisponibles => le RiskManager refuse (fail-closed).
        try:
            risk_stats = await self._trades.risk_stats()
        except Exception:  # noqa: BLE001 — un souci DB ne doit pas ouvrir de position
            logger.exception("Statistiques de risque indisponibles")
            risk_stats = None

        decision = self._risk.review(
            signal, account, positions, entry, stop_loss, risk_stats
        )
        await self._log_risk_decision(decision_id, decision, risk_stats)
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
            decimals=rules["decimal_places"],
        )
        broker_trade_id = _extract_deal_id(order) or (
            str(order["dealReference"]) if order.get("dealReference") else None
        )
        # L'arrondi au pas de lot MT5 peut réduire la taille : on journalise les
        # unités réellement exécutées, pas celles demandées.
        executed_units = float(order.get("size") or abs(decision.units))
        if decision.units < 0:
            executed_units = -executed_units

        trade_id = await self._trades.insert_open(
            signal,
            executed_units,
            float(order.get("level") or entry),
            stop_loss,
            take_profit,
            self._strategy.name,
            broker_trade_id,
        )
        await self._decisions.mark_executed(decision_id, trade_id)
        # Une seule entrée exécutée par bougie de déclenchement — la stratégie
        # est prévenue seulement quand l'ordre est réellement passé.
        # (trigger_bar_time: stratégie sweep ; m5_bar_time: stratégie scalp.)
        mark_consumed = getattr(self._strategy, "mark_signal_consumed", None)
        if callable(mark_consumed):
            mark_consumed(
                signal.features.get("trigger_bar_time")
                or signal.features.get("m5_bar_time")
            )
        out["status"] = "executed"
        out["trade_id"] = trade_id
        out["order"] = order
        out["broker_trade_id"] = broker_trade_id
        return out

    async def _close_expired_paper_positions(self) -> list[dict]:
        horizon_hours = self._strategy.paper_horizon_hours
        if (
            not self._strategy.paper_only
            or self._settings.broker_env != "demo"
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
            except BrokerError as exc:
                logger.warning("Clôture horizon échouée pour %s: %s", deal_id, exc)
                results.append(
                    {"trade_id": trade["id"], "status": "broker_error"}
                )
                continue

            exit_price = close_order.get("level")
            closed_at = _parse_broker_time(
                close_order.get("date") or close_order.get("dateUTC")
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
                self._notify_tuner(pnl, trade["side"], "HORIZON")
                await self._analyze_closed_trade(trade["id"], "HORIZON")
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

    async def close_profitable_positions(self) -> list[dict]:
        """Ferme toute position du bot dont le P&L net dépasse le seuil appris.

        C'est la sortie principale du mode scalp : peu importe l'ampleur du
        gain, une position en profit net (profit + swap, devise du compte,
        spread de clôture déjà compté par MT5) est fermée et le moteur repart
        chercher un signal. Le seuil `profit_close_min_net` sert de coussin
        contre la latence d'exécution et le slippage : sans lui, un P&L
        marginalement positif pourrait devenir négatif le temps que l'ordre de
        clôture atteigne le serveur.
        """
        s = self._settings
        if (
            not getattr(self._strategy, "close_on_profit", False)
            or not s.trading_enabled
            or (self._strategy.paper_only and s.broker_env != "demo")
        ):
            return []

        positions = await self._bot_positions()
        if not positions:
            return []
        min_net = float(
            getattr(self._strategy, "profit_close_min_net", s.profit_close_min_net)
        )

        results: list[dict] = []
        db_open: list[dict] | None = None
        for position in positions:
            net = float(position.get("profit") or 0.0) + float(
                position.get("swap") or 0.0
            )
            if net < min_net:
                continue
            ticket = str(position.get("ticket"))
            side = "BUY" if position.get("type") == 0 else "SELL"
            try:
                close_order = await self._broker.close_position_by_deal_id(ticket)
            except BrokerError as exc:
                logger.warning("Prise de profit échouée pour %s: %s", ticket, exc)
                results.append({"ticket": ticket, "status": "broker_error"})
                continue

            logger.info(
                "Prise de profit: position %s (%s) fermée avec net~%.2f %s",
                ticket,
                side,
                net,
                position.get("currency") or "",
            )
            # Le net observé (devise du compte) nourrit l'apprentissage : c'est
            # lui qui dit si le coussin couvre vraiment latence + slippage.
            self._notify_tuner(net, side, "PROFIT_TAKE")

            if db_open is None:
                db_open = await self._trades.open_trades()
            trade = next(
                (
                    t
                    for t in db_open
                    if str(t.get("broker_trade_id")) == ticket
                ),
                None,
            )
            exit_price = close_order.get("level")
            closed_at = _parse_broker_time(close_order.get("date")) or datetime.now(
                timezone.utc
            )
            if trade is not None and exit_price is not None:
                pnl = _compute_pnl(
                    trade["side"],
                    trade["units"],
                    trade["entry_price"],
                    float(exit_price),
                )
                await self._trades.close_trade(
                    trade["id"], float(exit_price), pnl, closed_at
                )
                await self._analyze_closed_trade(trade["id"], "PROFIT_TAKE")
                results.append(
                    {
                        "trade_id": trade["id"],
                        "ticket": ticket,
                        "status": "closed_in_profit",
                        "exit_price": float(exit_price),
                        "net_profit": round(net, 2),
                        "pnl": round(pnl, 2),
                    }
                )
            else:
                results.append(
                    {
                        "ticket": ticket,
                        "status": "closed_in_profit_untracked",
                        "net_profit": round(net, 2),
                    }
                )
        return results

    async def run_profit_monitor_loop(self) -> None:
        """Boucle rapide dédiée à la prise de profit.

        Tourne bien plus vite que la boucle de signal : une position qui passe
        en profit net est fermée en quelques secondes, pas au prochain step.
        """
        interval = max(1, self._settings.profit_check_interval_seconds)
        logger.info("Moniteur de prise de profit démarré (intervalle=%ss)", interval)
        while True:
            try:
                closed = await self.close_profitable_positions()
                if closed:
                    logger.info("Moniteur de profit: %s", closed)
            except BrokerError as exc:
                logger.warning("Moniteur de profit ignoré (broker): %s", exc)
            except Exception:  # noqa: BLE001 — the loop must never die silently
                logger.exception("Erreur inattendue dans le moniteur de profit")
            await asyncio.sleep(interval)

    async def paper_validation_status(self) -> dict:
        stats = await self._trades.paper_validation(self._strategy.name)
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

    async def promotion_eligibility_status(self) -> dict:
        paper = await self.paper_validation_status()
        shadow = await self._decisions.shadow_regime_status(REGIME_SHADOW_STRATEGY)
        requirements = [
            {
                "code": "EDGE_SCORE_CALIBRATED",
                "label": "Score d'edge calibré en probabilité",
                "passed": False,
                "detail": (
                    "Le score expected-return mesure un rendement attendu, pas une "
                    "probabilité de gain calibrée."
                ),
            },
            {
                "code": "PAPER_VALIDATION_COMPLETE",
                "label": "Validation paper terminée",
                "passed": bool(paper["eligible_for_review"]),
                "detail": (
                    f"{paper['closed_trades']} / "
                    f"{paper['target_closed_trades']} trades clôturés."
                ),
            },
            {
                "code": "REGIME_FILTER_VALIDATED",
                "label": "Filtre de régime validé historiquement",
                "passed": False,
                "detail": (
                    f"{shadow['total_decisions']} décision(s) shadow observée(s). "
                    "Le filtre reste diagnostique."
                ),
            },
            {
                "code": "DEMO_PAPER_LOCK",
                "label": "Verrou démo/paper actif",
                "passed": self._strategy.paper_only and self._settings.broker_env == "demo",
                "detail": (
                    f"Environnement={self._settings.broker_env}, "
                    f"paper_only={self._strategy.paper_only}, "
                    f"ordres={self._settings.trading_enabled}."
                ),
            },
        ]
        blockers = [item for item in requirements if not item["passed"]]
        return {
            "strategy": self._strategy.name,
            "promotion_eligible": False,
            "review_eligible": bool(paper["eligible_for_review"]) and not blockers,
            "automatic_live_promotion": False,
            "broker_env": self._settings.broker_env,
            "trading_enabled": self._settings.trading_enabled,
            "paper_only": self._strategy.paper_only,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "requirements": requirements,
            "blockers": blockers,
            "paper": paper,
            "regime_shadow": shadow,
        }

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
                    # Les clôtures broker (SL/TP surtout) alimentent aussi
                    # l'apprentissage — c'est là que sont les pertes.
                    if trade.get("strategy") == self._strategy.name:
                        self._notify_tuner(
                            pnl, trade["side"], close_event["source"]
                        )
                    await self._analyze_closed_trade(
                        trade["id"], close_event["source"]
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
                            "reason": "Aucune activité de clôture acceptée trouvée",
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
        # MT5 conserve l'historique des deals par position : une seule requête
        # suffit (pas de pagination jour par jour comme chez Capital.com).
        return await self._broker.find_close_event(
            str(broker_id), opened, trade["side"]
        )

    async def _resolve_deal_id(self, broker_trade_id: str | None) -> str | None:
        """Only numeric MT5 position tickets are usable against the terminal."""
        if not broker_trade_id:
            return None
        if str(broker_trade_id).startswith(("o_", "p_")):
            # Anciennes références Capital.com : plus résolubles depuis MT5 —
            # à solder manuellement via POST /trades/{id}/resolve.
            logger.warning(
                "Référence Capital.com héritée (%s) : résolution manuelle requise",
                broker_trade_id,
            )
            return None
        return str(broker_trade_id)

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
                "reason": "exit_price requis pour une clôture manuelle",
            }

        pnl = _compute_pnl(
            trade["side"],
            trade["units"],
            trade["entry_price"],
            exit_price,
        )
        await self._trades.close_trade(trade_id, exit_price, pnl, when)
        await self._analyze_closed_trade(trade_id, "MANUAL")
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
            except BrokerError as exc:
                logger.warning("Trade step ignoré (broker): %s", exc)
            except Exception:  # noqa: BLE001 — the loop must never die silently
                logger.exception("Erreur inattendue dans la boucle de trading")
            await asyncio.sleep(interval)
