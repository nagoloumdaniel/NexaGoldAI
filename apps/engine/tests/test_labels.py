"""Tests des labels par barrière (fondation du modèle de qualité de signal)."""

from datetime import datetime, timedelta

from app.learning.labels import (
    AMBIGUOUS,
    INVALID_DATA,
    STOP_FIRST,
    TARGET_FIRST,
    TIMEOUT,
    label_from_series,
    label_signal,
)

T0 = datetime(2026, 7, 28, 10, 0)


def bar(i: int, o, h, low, c):
    return {
        "time": (T0 + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%S"),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
    }


def flat(count: int, price: float = 100.0, start: int = 0):
    return [bar(start + i, price, price + 0.02, price - 0.02, price) for i in range(count)]


# stop_pct 0.001 sur entrée 100 -> stop 99.9, target (RR2) 100.2.


def test_target_first():
    series = flat(3) + [bar(3, 100.0, 100.25, 99.95, 100.2)]
    label = label_signal(series, "BUY", 0.001, 2.0, horizon_bars=10)
    assert label.outcome == TARGET_FIRST
    assert label.result_r == 2.0
    assert label.bars_to_outcome == 4
    assert label.entry_price == 100.0


def test_stop_first():
    series = flat(2) + [bar(2, 100.0, 100.05, 99.85, 99.9)]
    label = label_signal(series, "BUY", 0.001, 2.0, horizon_bars=10)
    assert label.outcome == STOP_FIRST
    assert label.result_r == -1.0


def test_ambiguous_same_bar_is_pessimistic():
    series = flat(1) + [bar(1, 100.0, 100.3, 99.8, 100.1)]  # touche les deux
    label = label_signal(series, "BUY", 0.001, 2.0, horizon_bars=10)
    assert label.outcome == AMBIGUOUS
    assert label.result_r == -1.0  # jamais compté favorable


def test_timeout_uses_final_close():
    series = flat(10, price=100.05)
    series[0] = bar(0, 100.0, 100.07, 99.98, 100.05)  # entrée à l'open 100
    label = label_signal(series, "BUY", 0.001, 2.0, horizon_bars=10)
    assert label.outcome == TIMEOUT
    assert label.result_r == 0.5  # +0.05 sur un risque de 0.1


def test_incomplete_horizon_is_invalid_not_timeout():
    series = flat(5)  # horizon 10 demandé, 5 bougies seulement
    label = label_signal(series, "BUY", 0.001, 2.0, horizon_bars=10)
    assert label.outcome == INVALID_DATA


def test_sell_mirror():
    series = flat(2, price=100.0) + [bar(2, 100.0, 100.02, 99.75, 99.8)]
    label = label_signal(series, "SELL", 0.001, 2.0, horizon_bars=10)
    assert label.outcome == TARGET_FIRST  # target SELL = 99.8


def test_label_from_series_excludes_signal_bar():
    # La bougie du signal (10:00) contient un mouvement qui toucherait le
    # target : elle NE DOIT PAS être utilisée (anti-fuite).
    signal_bar = bar(0, 100.0, 100.5, 99.9, 100.0)
    after = flat(10, price=100.0, start=1)
    label = label_from_series(
        [signal_bar] + after, signal_bar["time"], "BUY", 0.001, 2.0, horizon_bars=10
    )
    assert label.outcome == TIMEOUT  # rien touché après le signal
    assert label.mfe_r < 1.0


def test_invalid_inputs():
    assert label_signal([], "BUY", 0.001, 2.0).outcome == INVALID_DATA
    assert label_signal(flat(5), "BUY", 0.0, 2.0).outcome == INVALID_DATA
    assert label_from_series(flat(5), "pas-une-date", "BUY", 0.001, 2.0).outcome == INVALID_DATA
