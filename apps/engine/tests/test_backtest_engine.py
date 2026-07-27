"""Tests du backtest évènementiel : fills, brackets pessimistes, coûts,
absence de lookahead."""

from datetime import datetime, timedelta

from app.backtesting.engine import CostModel, EventBacktester, resample_m1
from app.strategy.base import Action, Signal, Strategy

T0 = datetime(2026, 7, 28, 8, 0)


def bar(i: int, o, h, low, c) -> dict:
    return {
        "time": (T0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%S"),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": 100,
    }


def flat_bars(count: int, price: float = 3300.0, start: int = 0) -> list[dict]:
    return [bar(start + i, price, price + 0.5, price - 0.5, price) for i in range(count)]


class StubStrategy(Strategy):
    """Émet un signal BUY/SELL à un index M1 précis (via l'heure de la bougie)."""

    name = "stub"
    paper_only = True
    extra_granularities = ()

    def __init__(self, fire_at_index: int, direction=Action.BUY,
                 stop_pct: float = 0.001, rr: float = 2.0):
        self.fire_time = (T0 + timedelta(minutes=fire_at_index)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        self.direction = direction
        self.stop_pct = stop_pct
        self.rr = rr
        self.consumed: list[str] = []

    def mark_signal_consumed(self, bar_time_iso):
        self.consumed.append(bar_time_iso)

    def evaluate(self, candles, macro_candles=None, extra=None) -> Signal:
        last_closed = candles[-2] if len(candles) > 1 else candles[-1]
        if last_closed["time"] != self.fire_time:
            return Signal(Action.HOLD, 0.0, "attente", {}, 0.0)
        return Signal(
            self.direction,
            0.8,
            "stub fire",
            {
                "stop_loss_pct": self.stop_pct,
                "risk_reward_ratio": self.rr,
                "trigger_bar_time": last_closed["time"],
                "setup_id": "stub-setup",
            },
            1.0,
        )


NO_COSTS = CostModel(spread_pct=0.0, slippage_pct=0.0, commission_pct=0.0)


def run_engine(m1, strategy, costs=NO_COSTS, **kwargs):
    engine = EventBacktester(strategy, costs, window_bars=70, **kwargs)
    return engine.run(m1)


def test_entry_fills_at_next_bar_open_no_lookahead():
    m1 = flat_bars(80)
    # La bougie 76 a une ouverture distincte pour vérifier le prix de fill.
    m1[76] = bar(76, 3305.0, 3306.0, 3304.0, 3305.5)
    strategy = StubStrategy(fire_at_index=75)
    report = run_engine(m1, strategy)
    assert report["trades"] + (1 if report["open_position_at_end"] else 0) == 1
    trade = report["trade_list"][0] if report["trade_list"] else report["open_position_at_end"]
    # Signal à la clôture de 75 -> fill à l'OUVERTURE de 76 (3305), pas à 3300.
    assert trade["entry_price"] == 3305.0
    assert trade["entry_time"] == m1[76]["time"]
    assert strategy.consumed == [m1[75]["time"]]


def test_take_profit_hit():
    m1 = flat_bars(80)
    strategy = StubStrategy(fire_at_index=75, stop_pct=0.001, rr=2.0)
    # Entrée à 3300 ; stop 3296.7, target 3306.6. La bougie 78 monte à 3307.
    m1[78] = bar(78, 3301.0, 3307.0, 3300.5, 3306.5)
    report = run_engine(m1, strategy)
    trade = report["trade_list"][0]
    assert trade["exit_reason"] == "TAKE_PROFIT"
    assert abs(trade["result_r"] - 2.0) < 0.01
    assert report["win_rate"] == 1.0


def test_stop_loss_hit():
    m1 = flat_bars(80)
    strategy = StubStrategy(fire_at_index=75, stop_pct=0.001, rr=2.0)
    m1[78] = bar(78, 3299.0, 3299.5, 3296.0, 3296.5)  # perce le stop 3296.7
    report = run_engine(m1, strategy)
    trade = report["trade_list"][0]
    assert trade["exit_reason"] == "STOP_LOSS"
    assert abs(trade["result_r"] + 1.0) < 0.01


def test_both_touched_same_bar_is_pessimistic_stop_first():
    m1 = flat_bars(80)
    strategy = StubStrategy(fire_at_index=75, stop_pct=0.001, rr=2.0)
    # Bougie 77 : touche à la fois le stop (3296.7) ET le target (3306.6).
    m1[77] = bar(77, 3300.0, 3308.0, 3295.0, 3305.0)
    report = run_engine(m1, strategy)
    trade = report["trade_list"][0]
    assert trade["exit_reason"] == "STOP_LOSS"
    assert trade["result_r"] < 0


def test_costs_reduce_result():
    m1 = flat_bars(80)
    m1[78] = bar(78, 3301.0, 3308.0, 3300.5, 3307.0)  # TP touché
    base = run_engine(m1, StubStrategy(75), NO_COSTS)
    costly = run_engine(
        m1, StubStrategy(75), CostModel(spread_pct=0.0002, slippage_pct=0.00005)
    )
    assert costly["trade_list"][0]["result_r"] < base["trade_list"][0]["result_r"]
    # L'entrée payée plus cher (demi-spread + slippage au-dessus de l'open).
    assert costly["trade_list"][0]["entry_price"] > base["trade_list"][0]["entry_price"]


def test_sell_direction_mirror():
    m1 = flat_bars(80)
    strategy = StubStrategy(fire_at_index=75, direction=Action.SELL, stop_pct=0.001)
    m1[78] = bar(78, 3299.0, 3299.5, 3292.0, 3293.0)  # target 3293.4 atteint
    report = run_engine(m1, strategy)
    trade = report["trade_list"][0]
    assert trade["direction"] == "SELL"
    assert trade["exit_reason"] == "TAKE_PROFIT"
    assert trade["result_r"] > 1.9


def test_timeout_exit():
    m1 = flat_bars(200)
    strategy = StubStrategy(fire_at_index=75, stop_pct=0.01, rr=50.0)
    report = run_engine(m1, strategy, max_holding_bars=20)
    trade = report["trade_list"][0]
    assert trade["exit_reason"] == "TIMEOUT"
    assert trade["holding_bars"] >= 20


def test_single_position_no_reentry_while_open():
    m1 = flat_bars(200)
    strategy = StubStrategy(fire_at_index=75, stop_pct=0.01, rr=50.0)
    report = run_engine(m1, strategy, max_holding_bars=1000)
    # Une seule position, encore ouverte à la fin : aucun autre trade.
    assert report["trades"] == 0
    assert report["open_position_at_end"] is not None


def test_resample_m1_to_m5():
    m1 = [bar(i, 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(12)]
    m5 = resample_m1(m1, 5)
    assert len(m5) == 3  # 08:00, 08:05, 08:10 (la dernière partielle incluse)
    first = m5[0]
    assert first["open"] == 100
    assert first["close"] == 104.5
    assert first["high"] == 105
    assert first["low"] == 99
    assert first["volume"] == 500
    assert m5[1]["time"].endswith("08:05:00")


def test_mfe_mae_tracked():
    m1 = flat_bars(80)
    strategy = StubStrategy(fire_at_index=75, stop_pct=0.001, rr=3.0)
    m1[77] = bar(77, 3300.0, 3305.0, 3299.0, 3301.0)  # excursion +1.5R / -0.3R
    m1[78] = bar(78, 3301.0, 3301.5, 3296.0, 3296.5)  # stop
    report = run_engine(m1, strategy)
    trade = report["trade_list"][0]
    assert trade["mfe_r"] > 1.0
    assert trade["mae_r"] <= -1.0  # le stop est l'excursion défavorable finale
