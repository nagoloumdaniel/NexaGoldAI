"""Risk gate: every signal must pass through here before becoming an order.

This module is deliberately conservative — when in doubt it rejects. The
engine survives on capital preservation, not on prediction quality.

Le RiskManager est INDÉPENDANT des stratégies et des modèles : aucune stratégie
ne peut élargir une limite, seulement réduire son exposition (multiplicateur
0..1). Les limites jour/semaine s'appuient sur le P&L réalisé en base (fourni
par le Trader via `risk_stats`) plus le flottant du compte — pas sur
`balance - equity` seul, qui repasse à zéro dès qu'une perte est réalisée.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.risk.kill_switch import KillSwitch
from app.strategy.base import Action, Signal


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    # Signed position size: positive = buy, negative = sell. The broker client
    # converts this to its own size/direction convention. 0 if rejected.
    units: float = 0.0


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class RiskManager:
    def __init__(self, settings: Settings, kill_switch: KillSwitch | None = None):
        self._settings = settings
        self.kill_switch = kill_switch

    def review(
        self,
        signal: Signal,
        account: dict,
        open_positions: list[dict],
        price: float,
        stop_loss_price: float,
        risk_stats: dict | None = None,
    ) -> RiskDecision:
        """`risk_stats` (fourni par le Trader depuis la DB) :
        realized_pnl_today / realized_pnl_week (devise du compte),
        consecutive_losses (série de clôtures perdantes la plus récente),
        last_loss_at (ISO UTC de la dernière clôture perdante).
        Absent (DB indisponible) => on ne trade pas : fail-closed.
        """
        s = self._settings

        if not s.trading_enabled:
            return RiskDecision(False, "Kill switch: TRADING_ENABLED=false")

        if self.kill_switch is not None and self.kill_switch.locked:
            return RiskDecision(
                False, f"Kill switch verrouillé: {self.kill_switch.reason}"
            )

        if signal.action == Action.HOLD:
            return RiskDecision(False, "Signal is HOLD")

        if len(open_positions) >= s.max_open_positions:
            return RiskDecision(False, f"Max open positions reached ({s.max_open_positions})")

        if risk_stats is None:
            # Sans statistiques de risque fiables, impossible de vérifier les
            # limites jour/semaine/série : on refuse plutôt que de supposer.
            return RiskDecision(
                False, "Statistiques de risque indisponibles (fail-closed)"
            )

        balance = float(account["balance"])
        nav = float(account.get("nav", balance))
        floating = nav - balance  # négatif quand les positions ouvertes perdent

        # -- Limite de perte quotidienne (réalisé + flottant) -----------------
        day_pnl = float(risk_stats.get("realized_pnl_today", 0.0)) + floating
        daily_loss_limit = balance * s.max_daily_loss_pct / 100.0
        if -day_pnl >= daily_loss_limit:
            reason = (
                f"Perte quotidienne {-day_pnl:.2f} >= limite "
                f"{daily_loss_limit:.2f} ({s.max_daily_loss_pct}%)"
            )
            if self.kill_switch is not None:
                self.kill_switch.lock(reason, source="auto")
            return RiskDecision(False, f"Daily loss limit hit: {reason}")

        # -- Limite de perte hebdomadaire -------------------------------------
        week_pnl = float(risk_stats.get("realized_pnl_week", 0.0)) + floating
        weekly_loss_limit = balance * s.max_weekly_loss_pct / 100.0
        if -week_pnl >= weekly_loss_limit:
            reason = (
                f"Perte hebdomadaire {-week_pnl:.2f} >= limite "
                f"{weekly_loss_limit:.2f} ({s.max_weekly_loss_pct}%)"
            )
            if self.kill_switch is not None:
                self.kill_switch.lock(reason, source="auto")
            return RiskDecision(False, f"Weekly loss limit hit: {reason}")

        # -- Série de pertes consécutives -------------------------------------
        consecutive = int(risk_stats.get("consecutive_losses", 0))
        if consecutive >= s.max_consecutive_losses:
            reason = (
                f"{consecutive} pertes consécutives >= limite "
                f"{s.max_consecutive_losses}"
            )
            if self.kill_switch is not None:
                self.kill_switch.lock(reason, source="auto")
            return RiskDecision(False, f"Consecutive losses limit hit: {reason}")

        # -- Cooldown après perte (indépendant de la stratégie) ----------------
        last_loss_at = _parse_utc(risk_stats.get("last_loss_at"))
        if last_loss_at is not None:
            minutes = (
                s.cooldown_after_consecutive_losses_minutes
                if consecutive >= 2
                else s.cooldown_after_loss_minutes
            )
            elapsed = datetime.now(timezone.utc) - last_loss_at
            if minutes > 0 and elapsed < timedelta(minutes=minutes):
                remaining = timedelta(minutes=minutes) - elapsed
                return RiskDecision(
                    False,
                    (
                        f"Cooldown après perte: encore "
                        f"{int(remaining.total_seconds() // 60) + 1} min "
                        f"({consecutive} perte(s) consécutive(s))"
                    ),
                )

        # -- Dimensionnement ---------------------------------------------------
        risk_per_unit = abs(price - stop_loss_price)
        if risk_per_unit <= 0:
            return RiskDecision(False, "Invalid stop loss (zero distance)")

        # Risk a fixed % of balance per trade, sized by stop distance.
        risk_budget = balance * s.max_risk_per_trade_pct / 100.0
        multiplier = float(signal.position_size)
        if not 0 < multiplier <= 1:
            return RiskDecision(False, "Invalid strategy position multiplier")
        units = round(risk_budget / risk_per_unit * multiplier, 1)
        if units <= 0:
            return RiskDecision(False, "Computed position size is zero")

        if signal.action == Action.SELL:
            units = -units

        return RiskDecision(
            True,
            f"Approved (strategy exposure {multiplier:.1%})",
            units=units,
        )
