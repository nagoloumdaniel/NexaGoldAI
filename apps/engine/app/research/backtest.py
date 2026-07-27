"""Walk-forward backtesting of the gold model.

Pipeline: candles -> features + labels -> walk-forward out-of-sample
predictions (LightGBM, no shuffling) -> classification metrics + a simple
long/short PnL backtest with transaction costs.

The point is honest, leak-free evaluation: every test bar is predicted by a
model that only saw strictly earlier bars.
"""

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import TimeSeriesSplit

from app.research.features import build_features
from app.research.labeling import CLASS_NAMES, DOWN, FLAT, UP, make_labels
from app.research.regime_validation import (
    build_historical_regime_features,
    evaluate_regime_gate,
    summarize_gate_impact,
)

# Bars per year, per granularity — used to annualise the Sharpe ratio.
_BARS_PER_YEAR = {
    "M1": 365 * 24 * 60,
    "M5": 365 * 24 * 12,
    "M15": 365 * 24 * 4,
    "M30": 365 * 24 * 2,
    "H1": 365 * 24,
}

DEFAULT_PARAMS = dict(
    n_estimators=400,
    learning_rate=0.05,
    num_leaves=31,
    min_child_samples=40,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    class_weight="balanced",
    random_state=42,
    n_jobs=-1,
    verbose=-1,
)


def build_dataset(
    df: pd.DataFrame,
    config: dict,
    macro_df: pd.DataFrame | None = None,
    rate_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Features + label (labelling method chosen by `config`) + next-bar return.

    `macro_df` is included as features only when `config["macro"]` is set;
    `rate_df` (real-rate series) only when `config["rates"]` is set.
    """
    use_macro = macro_df if config.get("macro") else None
    use_rates = rate_df if config.get("rates") else None
    feats = build_features(df, use_macro, use_rates)
    feats = pd.concat([feats, build_historical_regime_features(df)], axis=1)
    feats["label"] = make_labels(df, config)
    feats["next_ret"] = df["close"].pct_change().shift(-1)
    return feats.dropna()


def make_model(params: dict | None = None) -> LGBMClassifier:
    return LGBMClassifier(**(params or DEFAULT_PARAMS))


def walk_forward(
    data: pd.DataFrame, feature_cols: list[str], n_splits: int, embargo: int = 0
):
    """Out-of-sample predictions/probabilities via expanding-window CV.

    `embargo` (purge) drops that many bars between each train block and its
    test block, so labels that look `horizon` bars ahead can't leak training
    information into the test set.
    """
    X = data[feature_cols]  # keep column names so fit/predict stay consistent
    y = data["label"].astype(int).values
    oos_pred = np.full(len(data), -1, dtype=int)
    oos_proba = np.zeros((len(data), 3))

    for train_idx, test_idx in TimeSeriesSplit(
        n_splits=n_splits, gap=embargo
    ).split(X):
        model = make_model()
        model.fit(X.iloc[train_idx], y[train_idx])
        proba = model.predict_proba(X.iloc[test_idx])
        # Map model's present classes back onto fixed [DOWN, FLAT, UP] columns.
        for col, cls in enumerate(model.classes_):
            oos_proba[test_idx, cls] = proba[:, col]
        oos_pred[test_idx] = model.classes_[proba.argmax(axis=1)]

    mask = oos_pred >= 0
    return oos_pred, oos_proba, mask


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1).min())


def backtest_pnl(
    data: pd.DataFrame,
    oos_pred: np.ndarray,
    oos_proba: np.ndarray,
    mask: np.ndarray,
    granularity: str,
    cost_bps: float,
    confidence_threshold: float = 0.0,
    position_filter: np.ndarray | None = None,
) -> dict:
    sub = data[mask]
    pred = oos_pred[mask]
    confidence = oos_proba[mask].max(axis=1)
    # Only act on high-conviction signals; below the threshold we stay flat.
    directional = np.where(pred == UP, 1, np.where(pred == DOWN, -1, 0))
    position = np.where(confidence >= confidence_threshold, directional, 0)
    if position_filter is not None:
        if len(position_filter) != len(data):
            raise ValueError("Le filtre de position doit avoir la taille des donnees")
        position = np.where(np.asarray(position_filter, dtype=bool)[mask], position, 0)
    next_ret = sub["next_ret"].values

    gross = position * next_ret
    prev_position = np.concatenate([[0], position[:-1]])
    turnover = np.abs(position - prev_position)
    cost = turnover * (cost_bps / 1e4)
    net = gross - cost
    equity = np.cumprod(1 + net)

    active = position != 0
    wins = net[active & (net > 0)]
    losses = net[active & (net < 0)]
    bars_per_year = _BARS_PER_YEAR.get(granularity, 365 * 24 * 12)
    std = net.std()

    return {
        "bars": int(len(net)),
        "trades": int((turnover > 0).sum()),
        "exposure": float(active.mean()),
        "total_return": float(equity[-1] - 1) if len(equity) else 0.0,
        "sharpe_annualised": float(net.mean() / std * np.sqrt(bars_per_year))
        if std > 0
        else 0.0,
        "max_drawdown": _max_drawdown(equity) if len(equity) else 0.0,
        # None (not inf) when there are no losing bars — keeps the JSON valid.
        "profit_factor": float(wins.sum() / abs(losses.sum()))
        if losses.sum() != 0
        else None,
        "win_rate": float((net[active] > 0).mean()) if active.any() else 0.0,
        "mean_net_return_per_bar": float(net.mean()) if len(net) else 0.0,
        "expectancy_per_active_bar": float(net[active].mean())
        if active.any()
        else 0.0,
    }


# Confidence thresholds swept to find the best execution filter. 0.0 = trade
# every signal (old behaviour); higher = only high-conviction bets.
CONFIDENCE_THRESHOLDS = (0.0, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8)


def _submask(mask: np.ndarray, start_frac: float, end_frac: float) -> np.ndarray:
    """A contiguous (time-ordered) slice of the evaluated rows."""
    idx = np.flatnonzero(mask)
    lo = int(len(idx) * start_frac)
    hi = int(len(idx) * end_frac)
    out = np.zeros(len(mask), dtype=bool)
    out[idx[lo:hi]] = True
    return out


def _select_threshold(
    data: pd.DataFrame,
    oos_pred: np.ndarray,
    oos_proba: np.ndarray,
    validation_mask: np.ndarray,
    granularity: str,
    cost_bps: float,
    position_filter: np.ndarray | None = None,
) -> tuple[float, dict[str, float]]:
    sweep: dict[str, float] = {}
    best_threshold = 0.0
    best_sharpe = None
    for threshold in CONFIDENCE_THRESHOLDS:
        pnl = backtest_pnl(
            data,
            oos_pred,
            oos_proba,
            validation_mask,
            granularity,
            cost_bps,
            threshold,
            position_filter=position_filter,
        )
        sweep[str(threshold)] = pnl["sharpe_annualised"]
        if best_sharpe is None or pnl["sharpe_annualised"] > best_sharpe:
            best_sharpe = pnl["sharpe_annualised"]
            best_threshold = threshold
    return best_threshold, sweep


def run(
    data: pd.DataFrame,
    feature_cols: list[str],
    n_splits: int,
    granularity: str,
    cost_bps: float = 2.0,
    embargo: int = 0,
) -> dict:
    oos_pred, oos_proba, mask = walk_forward(data, feature_cols, n_splits, embargo)
    y_true = data["label"].astype(int).values[mask]
    y_pred = oos_pred[mask]

    dist = data["label"].astype(int).value_counts().sort_index()
    cm = confusion_matrix(y_true, y_pred, labels=[DOWN, FLAT, UP])

    # Pick the confidence threshold on an earlier VALIDATION slice, then report
    # PnL on a held-out later TEST slice — so the headline metric never sees the
    # data used to choose the threshold.
    val_mask = _submask(mask, 0.0, 0.6)
    test_mask = _submask(mask, 0.6, 1.0)

    best_threshold, sweep = _select_threshold(
        data,
        oos_pred,
        oos_proba,
        val_mask,
        granularity,
        cost_bps,
    )

    test_pnl = backtest_pnl(
        data, oos_pred, oos_proba, test_mask, granularity, cost_bps, best_threshold
    )

    regime_evaluation = evaluate_regime_gate(data, oos_pred, mask)
    regime_filter = regime_evaluation["allowed"].to_numpy(dtype=bool)
    gated_threshold, gated_sweep = _select_threshold(
        data,
        oos_pred,
        oos_proba,
        val_mask,
        granularity,
        cost_bps,
        position_filter=regime_filter,
    )
    filtered_same_threshold = backtest_pnl(
        data,
        oos_pred,
        oos_proba,
        test_mask,
        granularity,
        cost_bps,
        best_threshold,
        position_filter=regime_filter,
    )
    filtered_optimized = backtest_pnl(
        data,
        oos_pred,
        oos_proba,
        test_mask,
        granularity,
        cost_bps,
        gated_threshold,
        position_filter=regime_filter,
    )
    regime_validation = summarize_gate_impact(
        regime_evaluation,
        oos_pred,
        oos_proba,
        test_mask,
        best_threshold,
        test_pnl,
        filtered_same_threshold,
    )
    regime_validation.update(
        {
            "mode": "READ_ONLY",
            "baseline_confidence_threshold": best_threshold,
            "gated_confidence_threshold": gated_threshold,
            "gated_validation_sweep": gated_sweep,
            "baseline": test_pnl,
            "filtered_same_threshold": filtered_same_threshold,
            "filtered_optimized_threshold": filtered_optimized,
        }
    )

    return {
        "samples": int(len(data)),
        "evaluated": int(mask.sum()),
        "class_distribution": {CLASS_NAMES[k]: int(v) for k, v in dist.items()},
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro")),
        "confusion_matrix": {
            "labels": [CLASS_NAMES[c] for c in (DOWN, FLAT, UP)],
            "rows_true_cols_pred": cm.tolist(),
        },
        "best_confidence_threshold": best_threshold,
        "validation_sweep": sweep,
        "embargo": embargo,
        # Headline PnL = held-out test slice at the validation-chosen threshold.
        "pnl": test_pnl,
        "regime_gate_validation": regime_validation,
    }
