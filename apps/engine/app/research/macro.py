"""Macro features from a correlated instrument (e.g. EUR/USD as an inverse
proxy for the US dollar, the dominant driver of gold).

The macro series is aligned to the gold timeline (forward-filled), then turned
into causal features: macro returns over several horizons, macro volatility,
and the rolling gold/macro return correlation (regime signal).
"""

import pandas as pd


def build_rate_features(
    index: pd.DatetimeIndex, rate_df: pd.DataFrame
) -> pd.DataFrame:
    """Features depuis une série de TAUX (ex. taux réel US 10 ans, FRED DFII10).

    Contrairement à un prix, un taux réel peut être nul ou négatif : on utilise
    donc le NIVEAU et des VARIATIONS absolues (diff), jamais de pct_change.

    La série est journalière ; on la décale d'un jour avant de l'aligner sur la
    timeline de l'or (forward-fill), pour n'utiliser qu'une valeur déjà publiée
    — pas de lookahead.
    """
    # Valeur de la veille (publication FRED décalée), puis alignée par ffill.
    daily = rate_df["close"].shift(1)
    level = daily.reindex(index.union(daily.index)).sort_index().ffill().reindex(index)

    out = pd.DataFrame(index=index)
    out["rate_level"] = level
    out["rate_chg_1d"] = level.diff()
    out["rate_chg_5d"] = level.diff(5)
    out["rate_chg_20d"] = level.diff(20)
    # Régime : où se situe le taux dans sa fenêtre récente (z-score 60 obs).
    mean60 = level.rolling(60).mean()
    std60 = level.rolling(60).std()
    out["rate_z_60"] = (level - mean60) / std60.replace(0, float("nan"))
    return out


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
