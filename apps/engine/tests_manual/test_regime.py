"""Deterministic checks for market regime v1 (no network/DB).

Run: .venv\\Scripts\\python.exe -m tests_manual.test_regime
"""

from app.signals.regime import assess_regime_gate, classify_regime

base = {
    "data_quality_score": 1.0,
    "momentum_12": 0.01,
    "trend_strength": 0.0001,
    "zscore_20": 1.2,
    "volatility_ratio_5_20": 1.0,
    "atr_pct_14": 0.002,
    "warnings": [],
}

bull = classify_regime(base)
assert bull["regime"] == "BULLISH_TREND", bull
assert bull["trend"] == "BULLISH", bull

bear = classify_regime({**base, "momentum_12": -0.01, "trend_strength": -0.0001})
assert bear["regime"] == "BEARISH_TREND", bear
assert bear["trend"] == "BEARISH", bear

high_vol = classify_regime({**base, "volatility_ratio_5_20": 2.0})
assert high_vol["regime"] == "BULLISH_HIGH_VOLATILITY", high_vol
assert high_vol["volatility"] == "HIGH_VOLATILITY", high_vol

range_regime = classify_regime(
    {**base, "momentum_12": 0.0005, "trend_strength": 0.0, "zscore_20": 0.1}
)
assert range_regime["regime"] == "RANGE", range_regime

bad = classify_regime({**base, "data_quality_score": 0.4})
assert bad["regime"] == "LOW_DATA_QUALITY", bad

aligned = assess_regime_gate("BUY", bull, base)
assert aligned["allowed"] is True, aligned
assert aligned["agreement"] == "ALIGNED", aligned

conflict = assess_regime_gate("SELL", bull, base)
assert conflict["allowed"] is False, conflict
assert conflict["agreement"] == "CONFLICT", conflict

extreme_volatility = assess_regime_gate(
    "BUY",
    high_vol,
    {**base, "volatility_ratio_5_20": 2.3},
)
assert extreme_volatility["allowed"] is False, extreme_volatility
assert any("Volatilite extreme" in reason for reason in extreme_volatility["reasons"])

low_quality = assess_regime_gate(
    "BUY",
    bad,
    {**base, "data_quality_score": 0.4},
)
assert low_quality["allowed"] is False, low_quality

no_direction = assess_regime_gate("HOLD", bull, base)
assert no_direction["status"] == "NOT_APPLICABLE", no_direction

print("OK: regime v1 valide")
