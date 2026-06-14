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

from app.research.features import build_features, feature_columns
from app.research.labeling import CLASS_NAMES, DOWN, FLAT, UP, make_labels

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


def build_dataset(df: pd.DataFrame, horizon: int, threshold: float) -> pd.DataFrame:
    feats = build_features(df)
    label, fwd_ret = make_labels(df["close"], horizon, threshold)
    feats["label"] = label
    feats["fwd_ret"] = fwd_ret
    feats["next_ret"] = df["close"].pct_change().shift(-1)
    return feats.dropna()


def make_model(params: dict | None = None) -> LGBMClassifier:
    return LGBMClassifier(**(params or DEFAULT_PARAMS))


def walk_forward(data: pd.DataFrame, feature_cols: list[str], n_splits: int):
    """Out-of-sample predictions/probabilities via expanding-window CV."""
    X = data[feature_cols]  # keep column names so fit/predict stay consistent
    y = data["label"].astype(int).values
    oos_pred = np.full(len(data), -1, dtype=int)
    oos_proba = np.zeros((len(data), 3))

    for train_idx, test_idx in TimeSeriesSplit(n_splits=n_splits).split(X):
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
    mask: np.ndarray,
    granularity: str,
    cost_bps: float,
) -> dict:
    sub = data[mask]
    pred = oos_pred[mask]
    position = np.where(pred == UP, 1, np.where(pred == DOWN, -1, 0))
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
    }


def run(
    data: pd.DataFrame,
    feature_cols: list[str],
    n_splits: int,
    granularity: str,
    cost_bps: float = 2.0,
) -> dict:
    oos_pred, oos_proba, mask = walk_forward(data, feature_cols, n_splits)
    y_true = data["label"].astype(int).values[mask]
    y_pred = oos_pred[mask]

    dist = data["label"].astype(int).value_counts().sort_index()
    cm = confusion_matrix(y_true, y_pred, labels=[DOWN, FLAT, UP])

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
        "pnl": backtest_pnl(data, oos_pred, mask, granularity, cost_bps),
    }
