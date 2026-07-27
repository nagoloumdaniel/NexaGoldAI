"""Tests du générateur de dataset (capture des candidats + labels)."""

from app.learning.dataset_builder import collect_candidates
from tests.test_backtest_engine import StubStrategy, bar, flat_bars


def test_collects_and_labels_candidate():
    m1 = flat_bars(120)
    # Après le signal (bougie 75), le prix atteint le target RR2 (3306.6).
    m1[80] = bar(80, 3301.0, 3307.0, 3300.5, 3306.5)
    strategy = StubStrategy(fire_at_index=75, stop_pct=0.001, rr=2.0)
    rows = collect_candidates(strategy, m1, window_bars=70, horizon_bars=40)
    assert len(rows) == 1
    row = rows[0]
    assert row["direction"] == "BUY"
    assert row["outcome"] == "TARGET_FIRST"
    assert row["result_r"] == 2.0
    assert row["stop_loss_pct"] == 0.001
    assert row["signal_time"] == m1[75]["time"]
    assert row["hour_utc"] == 9  # 08:00 + 75 min


def test_deduplicates_by_setup_id():
    m1 = flat_bars(200)

    class RepeatingStub(StubStrategy):
        # Émet le même setup_id sur toutes les bougies 75..90.
        def evaluate(self, candles, macro_candles=None, extra=None):
            last = candles[-2]
            idx = int(last["time"][-5:-3])  # minute
            base = super().evaluate(candles, macro_candles, extra)
            if base.action.value != "HOLD":
                return base
            if 15 <= idx <= 30:  # 08:15..08:30
                from app.strategy.base import Action, Signal

                return Signal(
                    Action.BUY,
                    0.7,
                    "repeat",
                    {
                        "stop_loss_pct": 0.001,
                        "risk_reward_ratio": 2.0,
                        "setup_id": "same-setup",
                    },
                    1.0,
                )
            return base

    strategy = RepeatingStub(fire_at_index=999)  # le stub de base ne tire jamais
    rows = collect_candidates(strategy, m1, window_bars=70, horizon_bars=40)
    assert len(rows) == 1  # dédupliqué malgré ~16 émissions
    assert rows[0]["setup_id"] == "same-setup"


def test_insufficient_future_data_is_invalid():
    m1 = flat_bars(80)
    strategy = StubStrategy(fire_at_index=75, stop_pct=0.001, rr=2.0)
    # Seulement 4 bougies après le signal pour un horizon de 40.
    rows = collect_candidates(strategy, m1, window_bars=70, horizon_bars=40)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "INVALID_DATA"
