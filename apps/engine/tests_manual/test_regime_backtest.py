"""Deterministic checks for the read-only regime-gate backtest."""

import numpy as np
import pandas as pd

from app.research.backtest import backtest_pnl
from app.research.features import feature_columns
from app.research.labeling import DOWN, UP
from app.research.regime_validation import (
    REGIME_FEATURE_COLUMNS,
    build_historical_regime_features,
    evaluate_regime_gate,
    summarize_gate_impact,
)

index = pd.date_range("2026-01-01", periods=80, freq="h")
close = pd.Series(np.linspace(100.0, 120.0, len(index)), index=index)
candles = pd.DataFrame(
    {
        "open": close - 0.1,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": 100.0,
    },
    index=index,
)
regime_features = build_historical_regime_features(candles).dropna()
assert len(regime_features) > 0
assert set(REGIME_FEATURE_COLUMNS).issubset(regime_features.columns)
assert not set(REGIME_FEATURE_COLUMNS).intersection(feature_columns(regime_features))

mask = np.ones(len(regime_features), dtype=bool)
buy_pred = np.full(len(regime_features), UP, dtype=int)
sell_pred = np.full(len(regime_features), DOWN, dtype=int)

buy_evaluation = evaluate_regime_gate(regime_features, buy_pred, mask)
assert buy_evaluation["allowed"].all(), buy_evaluation["status"].value_counts()
assert set(buy_evaluation["agreement"]) == {"ALIGNED"}

sell_evaluation = evaluate_regime_gate(regime_features, sell_pred, mask)
assert not sell_evaluation["allowed"].any(), sell_evaluation["status"].value_counts()
assert set(sell_evaluation["agreement"]) == {"CONFLICT"}

data = regime_features.copy()
data["next_ret"] = 0.001
proba = np.zeros((len(data), 3))
proba[:, DOWN] = 0.9
proba[:, UP] = 0.1

baseline = backtest_pnl(
    data,
    sell_pred,
    proba,
    mask,
    "H1",
    cost_bps=2.0,
    confidence_threshold=0.8,
)
filtered = backtest_pnl(
    data,
    sell_pred,
    proba,
    mask,
    "H1",
    cost_bps=2.0,
    confidence_threshold=0.8,
    position_filter=sell_evaluation["allowed"].to_numpy(dtype=bool),
)
assert baseline["exposure"] == 1.0, baseline
assert filtered["exposure"] == 0.0, filtered
assert filtered["total_return"] == 0.0, filtered

impact = summarize_gate_impact(
    sell_evaluation,
    sell_pred,
    proba,
    mask,
    0.8,
    baseline,
    filtered,
)
assert impact["block_rate"] == 1.0, impact
assert impact["blocked_by_agreement"] == {"CONFLICT": len(data)}, impact
assert impact["improves_total_return"] is True, impact
assert impact["validation_decision"] == "REJECT_LIVE_INTEGRATION", impact

print("OK: regime gate backtest valide")
