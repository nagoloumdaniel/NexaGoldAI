"""Paper strategy, live lock and horizon-exit checks."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings, get_settings
from app.execution.trader import Trader
from app.research.dataset import load_candles
from app.risk.manager import RiskManager
from app.strategy.base import Action, AlwaysHold, Signal, Strategy
from app.strategy.expected_return_strategy import ExpectedReturnPaperStrategy
from app.strategy.factory import build_strategy

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "H1" / "expected_return_paper"


class FixedPaperStrategy(Strategy):
    name = "expected-return-paper"
    paper_only = True
    paper_horizon_hours = 24

    def evaluate(self, candles, macro_candles=None) -> Signal:
        return Signal(
            Action.BUY,
            0.7,
            "paper test",
            {
                "signal_kind": "expected_return",
                "expected_return": 0.004,
                "expected_return_threshold": 0.003,
                "position_size": 0.5,
                "paper_only": True,
            },
            position_size=0.5,
        )


class FakeDecisions:
    def __init__(self):
        self.rows = []

    async def insert(self, strategy, signal):
        decision_id = f"decision-{len(self.rows) + 1}"
        self.rows.append((decision_id, strategy, signal))
        return decision_id

    async def mark_executed(self, decision_id, trade_id):
        raise AssertionError("A live-blocked decision cannot execute")


class FakeTrades:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.closed = []

    async def open_trades(self):
        return self.rows

    async def close_trade(self, trade_id, exit_price, pnl, closed_at):
        self.closed.append((trade_id, exit_price, pnl, closed_at))

    async def paper_validation(self, strategy):
        return {
            "strategy": strategy,
            "total_trades": 0,
            "open_trades": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "profit_factor": None,
            "started_at": None,
            "last_closed_at": None,
        }


class FakeBroker:
    def __init__(self):
        self.price_calls = 0
        self.closed_deals = []

    async def get_candles(self, **kwargs):
        return [{"time": "2026-07-14T00:00:00", "close": 100.0}]

    async def get_price(self):
        self.price_calls += 1
        raise AssertionError("Paper-only live lock must run before price/order calls")

    async def close_position_by_deal_id(self, deal_id):
        self.closed_deals.append(deal_id)
        return {"dealReference": "close-ref"}

    async def get_deal_confirmation(self, deal_reference):
        return {
            "dealStatus": "ACCEPTED",
            "level": 105.0,
            "date": datetime.now(timezone.utc).isoformat(),
        }


async def main() -> None:
    # Factory refuses to even load the paper strategy in a live environment.
    try:
        build_strategy(
            Settings(
                strategy_name="expected_return_paper",
                capital_env="live",
            )
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected-return paper strategy loaded in live mode")

    live_broker = FakeBroker()
    live_decisions = FakeDecisions()
    live_trader = Trader(
        Settings(capital_env="live", trading_enabled=True),
        live_broker,
        FixedPaperStrategy(),
        RiskManager(Settings(capital_env="live", trading_enabled=True)),
        live_decisions,
        FakeTrades(),
    )
    blocked = await live_trader.step()
    assert blocked["status"] == "paper_only_blocked", blocked
    assert len(live_decisions.rows) == 2, live_decisions.rows
    assert live_decisions.rows[1][1] == "expected-return-paper-regime-shadow"
    assert live_decisions.rows[1][2].features["shadow_execution_allowed"] is False
    assert live_broker.price_calls == 0
    try:
        live_trader.set_strategy(AlwaysHold())
    except RuntimeError:
        pass
    else:
        raise AssertionError("paper strategy accepted an automatic non-paper swap")

    opened_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    trade = {
        "id": "trade-1",
        "strategy": "expected-return-paper",
        "side": "BUY",
        "units": 2.0,
        "entry_price": 100.0,
        "broker_trade_id": "deal-1",
        "opened_at": opened_at,
    }
    demo_broker = FakeBroker()
    demo_trades = FakeTrades([trade])
    demo_settings = Settings(capital_env="demo", trading_enabled=True)
    demo_trader = Trader(
        demo_settings,
        demo_broker,
        FixedPaperStrategy(),
        RiskManager(demo_settings),
        FakeDecisions(),
        demo_trades,
    )
    closures = await demo_trader._close_expired_paper_positions()
    assert demo_broker.closed_deals == ["deal-1"], demo_broker.closed_deals
    assert closures[0]["status"] == "closed_at_horizon", closures
    assert demo_trades.closed[0][2] == 10.0, demo_trades.closed

    settings = get_settings()
    candles_frame = await load_candles(settings, "H1")
    candles = [
        {
            "time": timestamp.isoformat(),
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
        }
        for timestamp, row in candles_frame.tail(200).iterrows()
    ]
    strategy = ExpectedReturnPaperStrategy(MODEL_DIR, "H1")
    signal = strategy.evaluate(candles)
    assert signal.action in {Action.BUY, Action.HOLD}, signal
    assert signal.action != Action.SELL, signal
    assert 0 < signal.position_size <= 1, signal
    assert signal.features["paper_only"] is True, signal.features
    assert signal.features["expected_return_threshold"] > 0, signal.features
    print(
        f"OK: paper action={signal.action.value} exposure={signal.position_size:.1%} "
        f"version={strategy.model_version}"
    )


if __name__ == "__main__":
    asyncio.run(main())
