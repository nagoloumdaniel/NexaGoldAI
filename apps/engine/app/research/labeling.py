"""Labelling: hausse / baisse / consolidation (3 classes).

Two methods, selected by a config dict:

- "fixed": UP/DOWN if the forward return over `horizon` bars exceeds
  ±`threshold`, else FLAT. Simple, but a fixed threshold ignores volatility.

- "triple_barrier": for each bar, an upper and lower barrier are placed at
  ±`vol_mult` × recent volatility, plus a vertical (time) barrier at `horizon`.
  The label is whichever horizontal barrier the price touches first (using
  intrabar high/low); FLAT if the vertical barrier is reached first. This is
  volatility-adaptive and path-dependent — a much more honest target.
"""

import numpy as np
import pandas as pd

DOWN, FLAT, UP = 0, 1, 2
CLASS_NAMES = {DOWN: "DOWN", FLAT: "FLAT", UP: "UP"}


def _fixed(close: pd.Series, horizon: int, threshold: float) -> pd.Series:
    fwd_ret = close.shift(-horizon) / close - 1
    label = pd.Series(FLAT, index=close.index, dtype="float64")
    label[fwd_ret > threshold] = UP
    label[fwd_ret < -threshold] = DOWN
    label.iloc[-horizon:] = pd.NA
    return label


def _triple_barrier(
    df: pd.DataFrame, horizon: int, vol_mult: float, vol_window: int
) -> pd.Series:
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    vol = (
        pd.Series(close).pct_change().rolling(vol_window).std().to_numpy()
    )
    n = len(close)
    labels = np.full(n, np.nan)

    for i in range(n):
        v = vol[i]
        # Need a valid volatility and a full forward window (no lookahead).
        if np.isnan(v) or v <= 0 or i + horizon >= n:
            continue
        upper = v * vol_mult
        lower = -v * vol_mult
        entry = close[i]
        outcome = FLAT
        for j in range(i + 1, i + horizon + 1):
            up_touch = high[j] / entry - 1 >= upper
            down_touch = low[j] / entry - 1 <= lower
            if up_touch and down_touch:
                outcome = DOWN  # both in one bar — assume the stop fired first
                break
            if up_touch:
                outcome = UP
                break
            if down_touch:
                outcome = DOWN
                break
        labels[i] = outcome

    return pd.Series(labels, index=df.index, dtype="float64")


def make_labels(df: pd.DataFrame, config: dict) -> pd.Series:
    method = config.get("labeling", "fixed")
    if method == "triple_barrier":
        return _triple_barrier(
            df,
            config["horizon"],
            config.get("vol_mult", 1.0),
            config.get("vol_window", 20),
        )
    return _fixed(df["close"], config["horizon"], config["threshold"])
