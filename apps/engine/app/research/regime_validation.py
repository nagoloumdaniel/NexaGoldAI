"""Causal historical evaluation of the live market-regime gate."""

from collections import Counter

import numpy as np
import pandas as pd

from app.research.labeling import DOWN, UP
from app.signals.regime import assess_regime_gate, classify_regime

REGIME_FEATURE_COLUMNS = (
    "_regime_momentum_12",
    "_regime_trend_strength",
    "_regime_zscore_20",
    "_regime_volatility_ratio_5_20",
    "_regime_atr_pct_14",
)

_SUMMARY_COLUMNS = {
    "momentum_12": "_regime_momentum_12",
    "trend_strength": "_regime_trend_strength",
    "zscore_20": "_regime_zscore_20",
    "volatility_ratio_5_20": "_regime_volatility_ratio_5_20",
    "atr_pct_14": "_regime_atr_pct_14",
}


def build_historical_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Recreate the live gate inputs at every bar without future data."""
    close = df["close"].astype(float)
    returns = close.pct_change()
    out = pd.DataFrame(index=df.index)

    out["_regime_momentum_12"] = close.pct_change(12)

    window = 20
    x = np.arange(window, dtype=float)
    weights = x - x.mean()
    denominator = float(np.dot(weights, weights))
    slope = close.rolling(window, min_periods=window).apply(
        lambda values: float(np.dot(weights, values) / denominator),
        raw=True,
    )
    out["_regime_trend_strength"] = slope / close.replace(0, np.nan)

    rolling_mean = close.rolling(window, min_periods=window).mean()
    rolling_std = close.rolling(window, min_periods=window).std(ddof=0)
    zscore = (close - rolling_mean) / rolling_std.replace(0, np.nan)
    out["_regime_zscore_20"] = zscore.where(rolling_std != 0, 0.0)

    vol_5 = returns.rolling(5, min_periods=5).std(ddof=0)
    vol_20 = returns.rolling(20, min_periods=20).std(ddof=0)
    out["_regime_volatility_ratio_5_20"] = vol_5 / vol_20.replace(0, np.nan)

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            df["high"].astype(float) - df["low"].astype(float),
            (df["high"].astype(float) - previous_close).abs(),
            (df["low"].astype(float) - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(14, min_periods=14).mean()
    out["_regime_atr_pct_14"] = atr / close.replace(0, np.nan)
    return out


def _summary_from_row(row: pd.Series) -> dict:
    summary: dict[str, float | None | list[str]] = {
        "data_quality_score": 1.0,
        "warnings": [],
    }
    for field, column in _SUMMARY_COLUMNS.items():
        value = row[column]
        summary[field] = None if pd.isna(value) else float(value)
    return summary


def evaluate_regime_gate(
    data: pd.DataFrame,
    oos_pred: np.ndarray,
    mask: np.ndarray,
) -> pd.DataFrame:
    """Evaluate BUY/SELL compatibility for every out-of-sample prediction."""
    missing = sorted(set(REGIME_FEATURE_COLUMNS) - set(data.columns))
    if missing:
        raise ValueError(f"Colonnes de regime absentes: {', '.join(missing)}")
    if len(data) != len(oos_pred) or len(data) != len(mask):
        raise ValueError("Predictions, masque et donnees doivent avoir la meme taille")

    size = len(data)
    allowed = np.zeros(size, dtype=bool)
    statuses = np.full(size, "UNEVALUATED", dtype=object)
    regimes = np.full(size, "UNKNOWN", dtype=object)
    agreements = np.full(size, "UNKNOWN", dtype=object)
    directions = np.full(size, "HOLD", dtype=object)
    block_reasons = np.empty(size, dtype=object)
    block_reasons[:] = [tuple()]

    for position in np.flatnonzero(mask):
        prediction = int(oos_pred[position])
        direction = "BUY" if prediction == UP else "SELL" if prediction == DOWN else "HOLD"
        summary = _summary_from_row(data.iloc[position])
        regime = classify_regime(summary)
        gate = assess_regime_gate(direction, regime, summary)

        allowed[position] = bool(gate["allowed"])
        statuses[position] = gate["status"]
        regimes[position] = regime["regime"]
        agreements[position] = gate["agreement"]
        directions[position] = direction
        block_reasons[position] = tuple(gate["reasons"])

    return pd.DataFrame(
        {
            "allowed": allowed,
            "status": statuses,
            "regime": regimes,
            "agreement": agreements,
            "direction": directions,
            "block_reasons": block_reasons,
        },
        index=data.index,
    )


def _counter(values) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(Counter(values).items())}


def summarize_gate_impact(
    evaluation: pd.DataFrame,
    oos_pred: np.ndarray,
    oos_proba: np.ndarray,
    test_mask: np.ndarray,
    confidence_threshold: float,
    baseline: dict,
    filtered: dict,
) -> dict:
    """Explain what the gate removed and how held-out PnL changed."""
    confidence = oos_proba.max(axis=1)
    directional = np.isin(oos_pred, [DOWN, UP])
    candidates = test_mask & directional & (confidence >= confidence_threshold)
    allowed = evaluation["allowed"].to_numpy(dtype=bool)
    blocked = candidates & ~allowed

    reason_counts: Counter = Counter()
    for reasons in evaluation.loc[blocked, "block_reasons"]:
        reason_counts.update(reasons)

    candidate_count = int(candidates.sum())
    blocked_count = int(blocked.sum())
    impact = {
        "total_return_delta": float(filtered["total_return"] - baseline["total_return"]),
        "sharpe_delta": float(
            filtered["sharpe_annualised"] - baseline["sharpe_annualised"]
        ),
        "max_drawdown_delta": float(
            filtered["max_drawdown"] - baseline["max_drawdown"]
        ),
        "trades_delta": int(filtered["trades"] - baseline["trades"]),
        "exposure_delta": float(filtered["exposure"] - baseline["exposure"]),
        "expectancy_active_bar_delta": float(
            filtered["expectancy_per_active_bar"]
            - baseline["expectancy_per_active_bar"]
        ),
    }
    profit_factor = filtered.get("profit_factor")
    promotion_checks = {
        "positive_total_return": filtered["total_return"] > 0,
        "positive_sharpe": filtered["sharpe_annualised"] > 0,
        "profit_factor_above_one": profit_factor is not None and profit_factor > 1,
        "minimum_turnover_events": filtered["trades"] >= 100,
    }
    passes_core_checks = all(promotion_checks.values())

    return {
        "candidate_directional_bars": candidate_count,
        "blocked_directional_bars": blocked_count,
        "block_rate": blocked_count / candidate_count if candidate_count else 0.0,
        "blocked_by_regime": _counter(evaluation.loc[blocked, "regime"]),
        "blocked_by_agreement": _counter(evaluation.loc[blocked, "agreement"]),
        "blocked_by_reason": {
            str(key): int(value) for key, value in sorted(reason_counts.items())
        },
        "impact_same_threshold": impact,
        "improves_total_return": filtered["total_return"] > baseline["total_return"],
        "improves_sharpe": filtered["sharpe_annualised"]
        > baseline["sharpe_annualised"],
        "reduces_max_drawdown": filtered["max_drawdown"] > baseline["max_drawdown"],
        "promotion_checks": promotion_checks,
        "validation_decision": (
            "CONTINUE_ROBUSTNESS_RESEARCH"
            if passes_core_checks
            else "REJECT_LIVE_INTEGRATION"
        ),
    }
