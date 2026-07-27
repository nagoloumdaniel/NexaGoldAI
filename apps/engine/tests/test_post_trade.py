"""Tests du calcul MFE/MAE de l'analyse post-trade."""

from app.analysis.post_trade import compute_excursions


def candles(rows):
    return [{"high": h, "low": low} for h, low in rows]


def test_buy_excursions():
    # Entrée 100, risque 2 (stop 98). Haut max 103 (+1.5R), bas min 99 (-0.5R).
    series = candles([(101, 99.5), (103, 100.2), (102, 99.0)])
    mfe, mae = compute_excursions(series, "BUY", 100.0, 2.0)
    assert mfe == 1.5
    assert mae == -0.5


def test_sell_excursions_mirror():
    # Entrée 100 SELL, risque 2. Bas min 96 (+2R), haut max 101.4 (-0.7R).
    series = candles([(100.8, 98.0), (101.4, 97.0), (100.2, 96.0)])
    mfe, mae = compute_excursions(series, "SELL", 100.0, 2.0)
    assert mfe == 2.0
    assert mae == -0.7


def test_invalid_risk_returns_none():
    series = candles([(101, 99)])
    assert compute_excursions(series, "BUY", 100.0, 0.0) == (None, None)
    assert compute_excursions([], "BUY", 100.0, 2.0) == (None, None)


def test_excursions_never_positive_mae_or_negative_mfe():
    # Le prix ne fait que monter : MAE reste 0 (jamais > 0), MFE > 0.
    series = candles([(101, 100.1), (102, 101.0)])
    mfe, mae = compute_excursions(series, "BUY", 100.0, 2.0)
    assert mfe == 1.0
    assert mae == 0.0
