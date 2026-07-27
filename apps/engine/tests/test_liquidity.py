"""Tests des niveaux de liquidité et de la détection de sweep."""

from app.strategy_v2.liquidity import (
    BUY,
    SELL,
    detect_sweep,
    find_liquidity_levels,
    most_recent_sweep,
)
from app.strategy_v2.market_structure import Swing, find_swings

ATR = 1.0


def candle(o, h, low, c, t=""):
    return {"time": t, "open": o, "high": h, "low": low, "close": c, "volume": 100}


def flat(price: float, count: int, spread: float = 0.3) -> list[dict]:
    return [candle(price, price + spread, price - spread, price) for _ in range(count)]


def test_equal_lows_merge_into_stronger_level():
    swings = [
        Swing(5, "t5", 100.1, "LOW"),
        Swing(9, "t9", 105.0, "HIGH"),
        Swing(14, "t14", 100.0, "LOW"),  # égalité avec le creux de l'index 5
        Swing(20, "t20", 108.0, "HIGH"),
    ]
    levels = find_liquidity_levels(swings, tolerance=0.2)
    lows = [level for level in levels if level.kind == "LOW"]
    assert len(lows) == 1
    assert lows[0].strength == 2
    assert lows[0].price == 100.0  # l'extrême du cluster porte les stops


def test_detect_sweep_buy_with_fast_reintegration():
    # 10 bougies stables à 101, puis perce du niveau 100 avec clôture de rejet.
    candles = flat(101.0, 10)
    candles.append(candle(101.0, 101.2, 99.5, 100.8))  # sweep + réintégration même bougie
    level = find_liquidity_levels([Swing(2, "t2", 100.0, "LOW")], 0.1)[0]
    event = detect_sweep(candles, level, ATR)
    assert event is not None
    assert event.direction == BUY
    assert event.speed_bars == 0
    assert event.depth == 0.5
    assert event.extreme == 99.5
    assert event.rejection_strength > 0.7  # clôture dans le haut de la bougie


def test_sweep_requires_reintegration():
    candles = flat(101.0, 10)
    # Perce puis les clôtures restent SOUS le niveau : cassure, pas sweep.
    candles.append(candle(101.0, 101.0, 99.5, 99.6))
    candles.append(candle(99.6, 99.8, 99.2, 99.4))
    candles.append(candle(99.4, 99.7, 99.0, 99.2))
    candles.append(candle(99.2, 99.6, 98.9, 99.1))
    level = find_liquidity_levels([Swing(2, "t2", 100.0, "LOW")], 0.1)[0]
    assert detect_sweep(candles, level, ATR) is None


def test_sweep_too_deep_is_a_breakdown():
    candles = flat(101.0, 10)
    candles.append(candle(101.0, 101.2, 97.0, 100.8))  # 3 ATR sous le niveau
    level = find_liquidity_levels([Swing(2, "t2", 100.0, "LOW")], 0.1)[0]
    assert detect_sweep(candles, level, ATR, max_depth_atr=1.5) is None


def test_sweep_too_shallow_is_noise():
    candles = flat(101.0, 10)
    candles.append(candle(101.0, 101.2, 99.95, 100.9))  # 0.05 ATR
    level = find_liquidity_levels([Swing(2, "t2", 100.0, "LOW")], 0.1)[0]
    assert detect_sweep(candles, level, ATR, min_depth_atr=0.1) is None


def test_sweep_reintegration_within_bar_budget():
    candles = flat(101.0, 10)
    candles.append(candle(100.5, 100.6, 99.4, 99.7))  # perce, clôture dessous
    candles.append(candle(99.7, 100.0, 99.5, 99.8))  # toujours dessous
    candles.append(candle(99.8, 100.9, 99.7, 100.7))  # réintègre (2 bougies après)
    level = find_liquidity_levels([Swing(2, "t2", 100.0, "LOW")], 0.1)[0]
    event = detect_sweep(candles, level, ATR, max_reintegration_bars=3)
    assert event is not None and event.speed_bars == 2
    # Avec un budget d'1 bougie, la réintégration arrive trop tard.
    assert detect_sweep(candles, level, ATR, max_reintegration_bars=1) is None


def test_sweep_sell_mirror():
    candles = flat(99.0, 10)
    candles.append(candle(99.0, 100.5, 98.8, 99.2))  # perce le sommet 100, rejet
    level = find_liquidity_levels([Swing(2, "t2", 100.0, "HIGH")], 0.1)[0]
    event = detect_sweep(candles, level, ATR)
    assert event is not None and event.direction == SELL
    assert event.extreme == 100.5


def test_old_sweep_outside_age_window_is_ignored():
    candles = flat(101.0, 10)
    candles.append(candle(101.0, 101.2, 99.5, 100.8))  # sweep...
    candles.extend(flat(101.0, 40))  # ...puis 40 bougies sans nouveau setup
    level = find_liquidity_levels([Swing(2, "t2", 100.0, "LOW")], 0.1)[0]
    assert detect_sweep(candles, level, ATR, max_age_bars=30) is None


def test_most_recent_sweep_prefers_latest_reintegration():
    candles = flat(101.0, 10)
    candles.append(candle(101.0, 101.2, 99.6, 100.8))  # sweep du niveau 100
    candles.extend(flat(101.5, 3))
    candles.append(candle(101.5, 101.7, 100.4, 101.4))  # sweep du niveau 100.9
    swings = [Swing(2, "t2", 100.0, "LOW"), Swing(8, "t8", 100.9, "LOW")]
    levels = find_liquidity_levels(swings, tolerance=0.1)
    event = most_recent_sweep(candles, levels, ATR, BUY)
    assert event is not None
    assert event.level == 100.9  # le setup le plus récent gagne


def test_levels_from_real_swing_detection():
    # Chemin en W : deux creux égaux -> un seul niveau LOW de force 2.
    path = [102, 101, 100, 101, 102, 103, 102, 101, 100.05, 101, 102, 103]
    candles = [candle(p, p + 0.2, p - 0.2, p) for p in path]
    swings = find_swings(candles, lookback=2)
    levels = find_liquidity_levels(swings, tolerance=0.3)
    lows = [level for level in levels if level.kind == "LOW"]
    assert len(lows) == 1 and lows[0].strength == 2
