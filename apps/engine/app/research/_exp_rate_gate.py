"""Expérience (jetable) : le taux réel comme FILTRE DE RÉGIME, pas comme feature.

Hypothèse testée : au lieu de donner le taux réel à l'arbre comme une feature de
plus (qui n'a pas créé d'edge — cf. backtest --rates), on s'en sert comme un
*gate* directionnel sur les décisions d'un modèle purement technique :

  taux réel en hausse  -> régime baissier or  -> on bloque les LONGS
  taux réel en baisse  -> régime haussier or  -> on bloque les SHORTS

Question falsifiable : ce filtre fait-il passer le profit factor au-dessus de 1
sur la slice de test held-out ? On compare, sur LA MÊME slice de test, le PnL du
modèle technique seul vs le même modèle gaté par le régime de taux.

Le seuil de confiance est choisi sur une slice de validation (60 % premières
barres) puis appliqué au test (40 % dernières) — pas de fuite. Jetable :
préfixe `_`, ne touche pas le pipeline de prod.

Usage : ./.venv/Scripts/python.exe -m app.research._exp_rate_gate
"""

import asyncio
import json

import numpy as np

from app.config import get_settings
from app.research import backtest as bt
from app.research.dataset import load_candles
from app.research.features import build_features, feature_columns
from app.research.labeling import DOWN, UP, make_labels
from app.research.macro import build_rate_features

GRANULARITY = "H1"
CONFIG = {"labeling": "fixed", "horizon": 24, "threshold": 0.002}
FOLDS = 5
COST_BPS = 2.0
THRESHOLDS = (0.0, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8)


def pnl(position: np.ndarray, next_ret: np.ndarray, cost_bps: float) -> dict:
    """PnL long/short avec coûts de transaction (même maths que backtest_pnl)."""
    gross = position * next_ret
    prev = np.concatenate([[0], position[:-1]])
    cost = np.abs(position - prev) * (cost_bps / 1e4)
    net = gross - cost
    equity = np.cumprod(1 + net)
    active = position != 0
    wins = net[active & (net > 0)]
    losses = net[active & (net < 0)]
    std = net.std()
    return {
        "sharpe": float(net.mean() / std * np.sqrt(365 * 24)) if std > 0 else 0.0,
        "total_return": float(equity[-1] - 1) if len(equity) else 0.0,
        "max_dd": float((equity / np.maximum.accumulate(equity) - 1).min())
        if len(equity)
        else 0.0,
        "profit_factor": float(wins.sum() / abs(losses.sum()))
        if losses.sum() != 0
        else None,
        "win_rate": float((net[active] > 0).mean()) if active.any() else 0.0,
        "exposure": float(active.mean()),
        "trades": int((np.abs(position - prev) > 0).sum()),
    }


def positions(pred, proba, threshold, regime=None):
    """Positions directionnelles, filtrées par confiance puis (option) par régime.

    regime > 0 = taux réel en hausse (bloque longs) ; < 0 = baisse (bloque shorts).
    NaN = pas d'avis -> aucun filtrage.
    """
    conf = proba.max(axis=1)
    directional = np.where(pred == UP, 1, np.where(pred == DOWN, -1, 0))
    pos = np.where(conf >= threshold, directional, 0)
    if regime is not None:
        rising = regime > 0
        falling = regime < 0
        pos = np.where((pos == 1) & rising, 0, pos)   # taux monte -> pas de long
        pos = np.where((pos == -1) & falling, 0, pos)  # taux baisse -> pas de short
    return pos


def slice_mask(n: int, lo: float, hi: float) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    m[int(n * lo) : int(n * hi)] = True
    return m


def best_threshold(pred, proba, next_ret, val, regime=None) -> float:
    best_t, best_s = 0.0, None
    for t in THRESHOLDS:
        s = pnl(positions(pred[val], proba[val], t, regime[val] if regime is not None else None),
                next_ret[val], COST_BPS)["sharpe"]
        if best_s is None or s > best_s:
            best_s, best_t = s, t
    return best_t


async def main() -> None:
    settings = get_settings()
    df = await load_candles(settings, GRANULARITY)
    rate_df = await load_candles(settings, "D", instrument=settings.rates_instrument)
    if df.empty or rate_df.empty:
        print(json.dumps({"error": "données manquantes (or H1 ou DFII10)"}))
        return

    feats = build_features(df)  # TECHNIQUE SEUL
    feats["label"] = make_labels(df, CONFIG)
    feats["next_ret"] = df["close"].pct_change().shift(-1)
    fcols = feature_columns(feats)

    core = feats[fcols + ["label", "next_ret"]].dropna()

    # Régimes de taux alignés sur la timeline de l'or (causaux, décalés d'1 jour).
    rates = build_rate_features(core.index, rate_df)

    oos_pred, oos_proba, mask = bt.walk_forward(core, fcols, FOLDS, embargo=CONFIG["horizon"])

    sub = core[mask]
    pred = oos_pred[mask]
    proba = oos_proba[mask]
    next_ret = sub["next_ret"].values
    n = len(pred)
    val = slice_mask(n, 0.0, 0.6)
    test = slice_mask(n, 0.6, 1.0)

    results = {}

    # --- Baseline : technique seul, pas de gate ---
    t = best_threshold(pred, proba, next_ret, val)
    results["baseline"] = {"threshold": t, **pnl(positions(pred[test], proba[test], t), next_ret[test], COST_BPS)}

    # --- Gate par régime de taux, sur plusieurs horizons de tendance ---
    for col in ("rate_chg_5d", "rate_chg_20d", "rate_z_60"):
        regime = rates[col].reindex(sub.index).values
        t = best_threshold(pred, proba, next_ret, val, regime)
        results[f"gate[{col}]"] = {
            "threshold": t,
            **pnl(positions(pred[test], proba[test], t, regime[test]), next_ret[test], COST_BPS),
        }

    print(json.dumps({"granularity": GRANULARITY, "samples": int(len(core)),
                       "test_bars": int(test.sum()), "results": results},
                      indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
