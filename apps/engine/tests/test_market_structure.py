"""Tests de la détection de structure (swings, labels, tendance, BOS/CHoCH)."""

from app.strategy_v2.market_structure import (
    BEARISH,
    BULLISH,
    RANGE,
    UNCERTAIN,
    analyze_structure,
    atr,
    find_swings,
    label_swings,
)


def candle(o: float, h: float, low: float, c: float, t: str = "") -> dict:
    return {"time": t, "open": o, "high": h, "low": low, "close": c, "volume": 100}


def from_path(points: list[float], spread: float = 0.4) -> list[dict]:
    """Bougies serrées autour de chaque point du chemin (o=c=p, mèches ±spread).

    Les extrema locaux du chemin deviennent ainsi des swings fractals nets,
    sans qu'une grande bougie d'impulsion n'englobe les creux du pullback.
    """
    return [
        candle(p, p + spread, p - spread, p, t=f"t{i}") for i, p in enumerate(points)
    ]


# Zigzag haussier : creux et sommets montants.
UPTREND = [100, 101, 103, 102, 101.5, 104, 106, 105, 104.5, 107, 109, 108, 107.5, 110, 112]
# Zigzag baissier symétrique.
DOWNTREND = [112, 111, 109, 110, 110.5, 108, 106, 107, 107.5, 105, 103, 104, 104.5, 102, 100]


def test_find_swings_alternates_and_detects_extrema():
    swings = find_swings(from_path(UPTREND), lookback=2)
    assert len(swings) >= 3
    for a, b in zip(swings[:-1], swings[1:], strict=False):
        assert a.kind != b.kind, "les swings doivent alterner HIGH/LOW"


def test_labels_uptrend_hh_hl():
    swings = label_swings(find_swings(from_path(UPTREND), lookback=2))
    labels = [s.label for s in swings if s.label]
    assert "HH" in labels and "HL" in labels
    assert "LL" not in labels


def test_analyze_bullish_and_bearish_trend():
    assert analyze_structure(from_path(UPTREND))["trend"] == BULLISH
    assert analyze_structure(from_path(DOWNTREND))["trend"] == BEARISH


def test_range_when_labels_conflict():
    # Sommets montants mais creux descendants : expansion / range.
    path = [100, 104, 99, 100, 105.5, 98, 99, 107, 96.5, 97]
    result = analyze_structure(from_path(path))
    assert result["trend"] in (RANGE, UNCERTAIN)


def test_uncertain_with_flat_series():
    flat = from_path([100.0] * 20, spread=0.0)
    assert analyze_structure(flat)["trend"] == UNCERTAIN


def test_bos_up_when_close_breaks_last_high():
    # Tendance haussière puis clôture au-dessus du dernier sommet confirmé.
    path = UPTREND + [113.5]
    result = analyze_structure(from_path(path))
    assert result["trend"] == BULLISH
    assert result["bos"] is not None and result["bos"]["direction"] == "UP"
    assert result["choch"] is None


def test_choch_down_when_close_breaks_last_higher_low():
    result = analyze_structure(from_path(UPTREND))
    last_low = result["last_low"].price
    path = UPTREND + [last_low - 3.0]
    broken = analyze_structure(from_path(path))
    # La cassure du dernier creux haussier est un CHoCH baissier.
    assert broken["choch"] is not None and broken["choch"]["direction"] == "DOWN"


def test_atr_positive_and_smooth():
    series = from_path(UPTREND * 3)
    value = atr(series, period=14)
    assert value > 0
    assert value < 10  # ordre de grandeur des variations du chemin
