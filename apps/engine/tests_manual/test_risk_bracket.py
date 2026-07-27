"""Deterministic check of the risk gate and bracket maths (no network/DB).

This is the path that will send real orders once the market is open and the
kill switch is lifted, so it gets verified offline.
Run: .venv\\Scripts\\python.exe -m tests_manual.test_risk_bracket
"""

from app.config import Settings
from app.execution.trader import compute_bracket
from app.risk.manager import RiskManager
from app.strategy.base import Action, Signal

ACCOUNT = {"balance": 1000.0, "nav": 1000.0}
BUY = Signal(Action.BUY, 0.8, "test buy")
# Statistiques de risque saines (le RiskManager est fail-closed sans elles).
STATS = {
    "realized_pnl_today": 0.0,
    "realized_pnl_week": 0.0,
    "consecutive_losses": 0,
    "last_loss_at": None,
}

# Bracket maths
sl, tp = compute_bracket(Action.BUY, 4200.0, 0.005, 1.5)
assert abs(sl - 4179.0) < 1e-6, sl
assert abs(tp - 4231.5) < 1e-6, tp
sl_s, tp_s = compute_bracket(Action.SELL, 4200.0, 0.005, 1.5)
assert abs(sl_s - 4221.0) < 1e-6, sl_s
assert abs(tp_s - 4168.5) < 1e-6, tp_s

# Kill switch: trading disabled -> always rejected
risk_off = RiskManager(Settings(trading_enabled=False))
d = risk_off.review(BUY, ACCOUNT, [], 4200.0, sl, STATS)
assert not d.approved and "Kill switch" in d.reason, d

# Enabled: position sized from risk budget and stop distance
risk_on = RiskManager(
    Settings(
        trading_enabled=True,
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
        max_open_positions=1,
    )
)
d = risk_on.review(BUY, ACCOUNT, [], 4200.0, sl, STATS)
# risk budget = 1% of 1000 = 10 ; stop distance = 21 ; units = 10/21 ≈ 0.5
assert d.approved, d
assert abs(d.units - 0.5) < 1e-9, d.units

# Fail-closed: pas de statistiques de risque -> refus
d = risk_on.review(BUY, ACCOUNT, [], 4200.0, sl, None)
assert not d.approved and "fail-closed" in d.reason, d

# Strategy volatility targeting scales the normal risk budget without leverage.
half_size_buy = Signal(Action.BUY, 0.8, "test half size", position_size=0.5)
d = risk_on.review(half_size_buy, ACCOUNT, [], 4200.0, sl, STATS)
assert d.approved, d
assert d.units == 0.2, d.units
assert "50.0%" in d.reason, d.reason

# Max open positions enforced
d = risk_on.review(BUY, ACCOUNT, [{"x": 1}], 4200.0, sl, STATS)
assert not d.approved and "Max open positions" in d.reason, d

# Daily loss limit: NAV far below balance (floating loss) -> rejected
d = risk_on.review(BUY, {"balance": 1000.0, "nav": 900.0}, [], 4200.0, sl, STATS)
assert not d.approved and "loss limit" in d.reason, d

# Daily loss limit: pertes RÉALISÉES avec equity revenue au niveau du solde
# (le cas que l'ancienne implémentation balance-nav ne voyait pas).
d = risk_on.review(
    BUY, ACCOUNT, [], 4200.0, sl, {**STATS, "realized_pnl_today": -31.0}
)
assert not d.approved and "loss limit" in d.reason, d

print("OK: risk gate + bracket valides")
