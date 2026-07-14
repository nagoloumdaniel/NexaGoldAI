"""Deterministic checks for structured signal generation (no network/DB).

Run: .venv\\Scripts\\python.exe -m tests_manual.test_structured_signal
"""

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.signals.structured import build_structured_signal
from app.strategy.base import Action, Signal

settings = Settings(
    epic="GOLD",
    model_granularity="H1",
    decision_candles=2,
    stop_loss_pct=0.01,
    risk_reward_ratio=2.0,
    trading_enabled=False,
)
candles = [
    {"time": datetime.now(timezone.utc).isoformat(), "close": 100.0},
    {"time": datetime.now(timezone.utc).isoformat(), "close": 101.0},
]
price = {"bid": 101.0, "ask": 101.5, "tradeable": True}

buy = build_structured_signal(
    settings,
    "test",
    Signal(Action.BUY, 0.8, "buy reason"),
    candles,
    price,
    "champion-test",
)
assert buy["direction"] == "BUY", buy
assert buy["recommended_entry"] == 101.5, buy
assert buy["recommended_sl"] == 100.485, buy
assert buy["recommended_tp"] == 103.53, buy
assert buy["execution_mode"] == "PAPER", buy
assert buy["model_version"] == "champion-test", buy
assert buy["regime_gate"]["allowed"] is True, buy

expected_return = build_structured_signal(
    settings,
    "expected-return-paper",
    Signal(
        Action.BUY,
        0.7,
        "expected-return buy",
        features={
            "signal_kind": "expected_return",
            "expected_return": 0.004,
            "expected_value_after_costs": 0.0035,
            "stop_loss_pct": 0.012,
            "risk_reward_ratio": 3.0,
            "paper_only": True,
        },
        position_size=0.6,
    ),
    candles,
    price,
    "paper-test",
)
assert expected_return["execution_mode"] == "PAPER", expected_return
assert expected_return["expected_move"] == 0.004, expected_return
assert expected_return["expected_value_after_costs"] == 0.0035, expected_return
assert expected_return["recommended_exposure"] == 0.6, expected_return
assert expected_return["risk_reward_ratio"] == 3.0, expected_return
assert expected_return["recommended_sl"] == 100.282, expected_return
assert expected_return["regime_gate"]["status"] == "NOT_APPLICABLE", expected_return

hold = build_structured_signal(
    settings,
    "test",
    Signal(Action.HOLD, 1.0, "hold reason"),
    candles,
    price,
    None,
)
assert hold["direction"] == "NO_TRADE", hold
assert "La strategie a refuse de trader" in hold["reasons"], hold

bad_data = build_structured_signal(
    settings,
    "test",
    Signal(Action.BUY, 0.9, "buy reason"),
    [],
    price,
    None,
)
assert bad_data["direction"] == "NO_TRADE", bad_data
assert bad_data["data_quality_score"] == 0.0, bad_data
assert bad_data["regime_gate"]["status"] == "BLOCKED", bad_data

stale_time = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
stale = build_structured_signal(
    settings,
    "test",
    Signal(Action.BUY, 0.9, "buy reason"),
    [
        {"time": stale_time, "close": 100.0},
        {"time": stale_time, "close": 101.0},
    ],
    price,
    None,
)
assert stale["direction"] == "NO_TRADE", stale
assert stale["regime_gate"]["status"] == "BLOCKED", stale

trending_candles = [
    {
        "time": datetime.now(timezone.utc).isoformat(),
        "open": 100.0 + index,
        "high": 101.2 + index,
        "low": 99.8 + index,
        "close": 101.0 + index,
    }
    for index in range(30)
]
conflict = build_structured_signal(
    settings,
    "test",
    Signal(Action.SELL, 0.9, "sell reason"),
    trending_candles,
    {"bid": 130.0, "ask": 130.5, "tradeable": True},
    None,
)
assert conflict["direction"] == "NO_TRADE", conflict
assert conflict["regime_gate"]["agreement"] == "CONFLICT", conflict

print("OK: structured signal valide")
