"""Technical features for the gold model.

Every feature is causal — it uses only information available up to and
including the current bar, so there is no lookahead leaking future prices.
"""

import numpy as np
import pandas as pd

from app.research.macro import build_macro_features

# Columns produced here that are NOT model inputs (kept for labels/PnL).
NON_FEATURE = {"label", "fwd_ret", "next_ret"}


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period).mean()


def build_features(
    df: pd.DataFrame, macro_df: pd.DataFrame | None = None
) -> pd.DataFrame:
    close = df["close"]
    out = pd.DataFrame(index=df.index)

    # Momentum / returns over several horizons
    out["ret_1"] = close.pct_change()
    out["ret_3"] = close.pct_change(3)
    out["ret_6"] = close.pct_change(6)
    out["ret_12"] = close.pct_change(12)

    # Distance to moving averages
    for n in (5, 10, 20, 50):
        out[f"sma_ratio_{n}"] = close / close.rolling(n).mean() - 1

    # Momentum acceleration (change in short-horizon return)
    out["ret_accel"] = out["ret_3"] - out["ret_6"]

    # Realised volatility, multi-scale + ratio (regime)
    for n in (5, 10, 20, 50):
        out[f"vol_{n}"] = out["ret_1"].rolling(n).std()
    out["vol_ratio"] = out["vol_5"] / out["vol_50"].replace(0, np.nan)

    # Return distribution shape
    out["skew_20"] = out["ret_1"].rolling(20).skew()

    # ATR normalised by price
    out["atr_14"] = _atr(df, 14) / close

    # RSI at two periods (scaled to 0..1)
    out["rsi_7"] = _rsi(close, 7) / 100.0
    out["rsi_14"] = _rsi(close, 14) / 100.0

    # Donchian position: where close sits in the recent range (0..1)
    for n in (20, 50):
        hi = df["high"].rolling(n).max()
        lo = df["low"].rolling(n).min()
        out[f"donchian_{n}"] = (close - lo) / (hi - lo).replace(0, np.nan)

    # MACD, normalised by price
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    out["macd"] = macd / close
    out["macd_hist"] = (macd - signal) / close

    # Bollinger band position
    m20 = close.rolling(20).mean()
    s20 = close.rolling(20).std()
    out["bb_pos"] = (close - m20) / (2 * s20).replace(0, np.nan)

    # Candle shape
    out["hl_range"] = (df["high"] - df["low"]) / close
    out["body"] = (close - df["open"]) / close

    # Volume anomaly
    vmean = df["volume"].rolling(20).mean()
    vstd = df["volume"].rolling(20).std()
    out["vol_z"] = (df["volume"] - vmean) / vstd.replace(0, np.nan)

    # Session / time-of-day (cyclical encoding)
    hour = df.index.hour + df.index.minute / 60.0
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["dow"] = df.index.dayofweek.astype(float)

    # Macro features (optional) — only added when a macro series is supplied.
    if macro_df is not None and not macro_df.empty:
        macro = build_macro_features(df.index, macro_df, close)
        out = pd.concat([out, macro], axis=1)

    return out


def feature_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c not in NON_FEATURE]
