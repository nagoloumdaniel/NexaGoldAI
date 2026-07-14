"""Deterministic checks for compact XAU/USD math features (no network/DB).

Run: .venv\\Scripts\\python.exe -m tests_manual.test_math_features
"""

from math import log

from app.signals.math_features import build_math_summary

candles = []
for i in range(60):
    close = 100.0 + i
    candles.append(
        {
            "time": f"2026-01-01T{i % 24:02d}:00:00",
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100 + i,
        }
    )

summary = build_math_summary(candles, min_count=50)

assert summary["data_quality_score"] == 1.0, summary
assert abs(summary["simple_return_1"] - (159 / 158 - 1)) < 1e-8, summary
assert abs(summary["log_return_1"] - log(159 / 158)) < 1e-8, summary
assert summary["momentum_3"] > 0, summary
assert summary["momentum_12"] > 0, summary
assert summary["regression_slope_20"] == 1.0, summary
assert summary["trend_strength"] > 0, summary
assert summary["atr_14"] is not None and summary["atr_14"] > 0, summary
assert summary["zscore_20"] is not None and summary["zscore_20"] > 0, summary

short = build_math_summary(candles[:2], min_count=50)
assert short["data_quality_score"] < 1.0, short
assert short["warnings"], short

empty = build_math_summary([], min_count=50)
assert empty["data_quality_score"] == 0.0, empty
assert empty["simple_return_1"] is None, empty

print("OK: math features valides")
