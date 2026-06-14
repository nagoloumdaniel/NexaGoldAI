"""Macro features from a correlated instrument (e.g. EUR/USD as an inverse
proxy for the US dollar, the dominant driver of gold).

The macro series is aligned to the gold timeline (forward-filled), then turned
into causal features: macro returns over several horizons, macro volatility,
and the rolling gold/macro return correlation (regime signal).
"""

import pandas as pd


def build_macro_features(
    index: pd.DatetimeIndex, macro_df: pd.DataFrame, gold_close: pd.Series
) -> pd.DataFrame:
    macro_close = macro_df["close"].reindex(index, method="ffill")
    macro_ret = macro_close.pct_change()
    gold_ret = gold_close.pct_change()

    out = pd.DataFrame(index=index)
    out["macro_ret_1"] = macro_ret
    out["macro_ret_6"] = macro_close.pct_change(6)
    out["macro_ret_12"] = macro_close.pct_change(12)
    out["macro_vol_20"] = macro_ret.rolling(20).std()
    out["macro_corr_50"] = gold_ret.rolling(50).corr(macro_ret)
    return out
