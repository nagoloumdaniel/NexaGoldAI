"""Risk gate: every signal must pass through here before becoming an order.

This module is deliberately conservative — when in doubt it rejects. The
engine survives on capital preservation, not on prediction quality.
"""

from dataclasses import dataclass

from app.config import Settings
from app.strategy.base import Action, Signal


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    # Signed position size: positive = buy, negative = sell. The broker client
    # converts this to its own size/direction convention. 0 if rejected.
    units: float = 0.0


class RiskManager:
    def __init__(self, settings: Settings):
        self._settings = settings

    def review(
        self,
        signal: Signal,
        account: dict,
        open_positions: list[dict],
        price: float,
        stop_loss_price: float,
    ) -> RiskDecision:
        s = self._settings

        if not s.trading_enabled:
            return RiskDecision(False, "Kill switch: TRADING_ENABLED=false")

        if signal.action == Action.HOLD:
            return RiskDecision(False, "Signal is HOLD")

        if len(open_positions) >= s.max_open_positions:
            return RiskDecision(False, f"Max open positions reached ({s.max_open_positions})")

        balance = float(account["balance"])
        # OANDA resets 'pl' daily stats elsewhere; until daily P&L tracking is
        # wired to the database, use unrealized + realized P&L vs balance.
        nav = float(account.get("NAV", balance))
        daily_loss_limit = balance * s.max_daily_loss_pct / 100.0
        if balance - nav >= daily_loss_limit:
            return RiskDecision(False, f"Daily loss limit hit ({s.max_daily_loss_pct}%)")

        risk_per_unit = abs(price - stop_loss_price)
        if risk_per_unit <= 0:
            return RiskDecision(False, "Invalid stop loss (zero distance)")

        # Risk a fixed % of balance per trade, sized by stop distance.
        risk_budget = balance * s.max_risk_per_trade_pct / 100.0
        units = round(risk_budget / risk_per_unit, 1)
        if units <= 0:
            return RiskDecision(False, "Computed position size is zero")

        if signal.action == Action.SELL:
            units = -units

        return RiskDecision(True, "Approved", units=units)
