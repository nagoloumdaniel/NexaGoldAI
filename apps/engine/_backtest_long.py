"""Jetable : backtest read-only HONNETE sur toute la profondeur disponible.

Ajoute deux garde-fous a la methodo de app.research.run :
  1. Sensibilite aux couts : PnL recalcule a 2 / 5 / 10 / 15 bps (le 2 bps par
     defaut est optimiste pour l'or chez Capital.com).
  2. Robustesse par fenetre : seuil de confiance choisi sur les 50% premiers
     (validation), puis PnL rapporte sur N fenetres sequentielles du reste —
     pour voir si l'edge tient periode apres periode, pas sur une seule tranche.

N'ecrit AUCUN fichier (ne touche pas au modele live).
Usage: .venv\\Scripts\\python.exe _backtest_long.py H1 [n_windows]
"""
import asyncio
import sys

import numpy as np

from app.config import get_settings
from app.research import backtest as bt
from app.research.dataset import load_candles
from app.research.features import feature_columns

CONFIG = {"labeling": "fixed", "horizon": 24, "threshold": 0.002,
          "vol_mult": 1.0, "vol_window": 20, "macro": False}
FOLDS = 5
COST_GRID = [2.0, 5.0, 10.0, 15.0]


def _window_mask(mask, start_frac, end_frac):
    idx = np.flatnonzero(mask)
    lo, hi = int(len(idx) * start_frac), int(len(idx) * end_frac)
    out = np.zeros(len(mask), dtype=bool)
    out[idx[lo:hi]] = True
    return out


async def main() -> None:
    granularity = sys.argv[1] if len(sys.argv) > 1 else "H1"
    n_windows = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    settings = get_settings()
    df = await load_candles(settings, granularity)
    if df.empty or len(df) < 500:
        print(f"Donnees insuffisantes ({len(df)} bougies)")
        return

    print(f"=== {granularity} : {len(df)} bougies, du {df.index[0]} au {df.index[-1]} ===")
    years = (df.index[-1] - df.index[0]).days / 365.25
    print(f"    (~{years:.1f} ans d'historique)\n")

    data = bt.build_dataset(df, CONFIG, None)
    feature_cols = feature_columns(data)
    oos_pred, oos_proba, mask = bt.walk_forward(data, feature_cols, FOLDS, CONFIG["horizon"])

    # Seuil choisi sur la 1ere moitie (validation), jamais sur le test.
    val_mask = _window_mask(mask, 0.0, 0.5)
    best_thr, best_val = 0.0, None
    print("--- Choix du seuil sur VALIDATION (1ere moitie) ---")
    for thr in bt.CONFIDENCE_THRESHOLDS:
        s = bt.backtest_pnl(data, oos_pred, oos_proba, val_mask, granularity, 5.0, thr)
        print(f"  seuil {thr}: Sharpe {s['sharpe_annualised']:.2f}")
        if best_val is None or s["sharpe_annualised"] > best_val:
            best_val, best_thr = s["sharpe_annualised"], thr
    print(f"  => seuil retenu : {best_thr} (Sharpe val {best_val:.2f})\n")

    # 1. Sensibilite aux couts sur tout le held-out (2nde moitie).
    test_mask = _window_mask(mask, 0.5, 1.0)
    print("--- Sensibilite aux COUTS (held-out, 2nde moitie) ---")
    print("  bps |  Sharpe | Rendement | MaxDD  | WinRate | PF    | Trades")
    for c in COST_GRID:
        p = bt.backtest_pnl(data, oos_pred, oos_proba, test_mask, granularity, c, best_thr)
        pf = f"{p['profit_factor']:.2f}" if p["profit_factor"] else "n/a"
        print(f"  {c:>4.0f}| {p['sharpe_annualised']:>7.2f} | "
              f"{p['total_return']*100:>8.2f}% | {p['max_drawdown']*100:>6.1f}% | "
              f"{p['win_rate']*100:>6.1f}% | {pf:>5} | {p['trades']}")

    # 2. Robustesse par fenetre sequentielle (a 5 bps, cout median realiste).
    print(f"\n--- Robustesse par fenetre (held-out decoupe en {n_windows}, a 5 bps) ---")
    print("  fenetre |  Sharpe | Rendement | WinRate | Trades")
    edges = np.linspace(0.5, 1.0, n_windows + 1)
    for i in range(n_windows):
        wm = _window_mask(mask, edges[i], edges[i + 1])
        p = bt.backtest_pnl(data, oos_pred, oos_proba, wm, granularity, 5.0, best_thr)
        print(f"  {i+1}/{n_windows}     | {p['sharpe_annualised']:>7.2f} | "
              f"{p['total_return']*100:>8.2f}% | {p['win_rate']*100:>6.1f}% | {p['trades']}")


asyncio.run(main())
