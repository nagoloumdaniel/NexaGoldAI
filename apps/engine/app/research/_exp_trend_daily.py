"""Expérience (jetable) : trend-following sur l'or JOURNALIER, ~24 ans.

Le modèle de classification intraday n'a pas d'edge (PF<1 même à coût mini, cf.
mémoire). Hypothèse différente, mécanisme économique réel : l'or TEND sur le long
terme → des règles de suivi de tendance / breakout, en daily, ajoutent-elles de la
valeur ?

Discipline anti-cherry-picking :
  - on teste TOUTE une grille de règles classiques (pas juste la meilleure),
  - on compare TOUJOURS au buy-and-hold (l'or a monté → un biais long paraît bon),
  - on découpe en DEUX MOITIÉS pour voir si le signal tient à travers les époques.

Données : Yahoo Finance GC=F (futures or, OHLC réels, ~2000→présent), via httpx.
Jetable (préfixe `_`), ne touche pas le pipeline de prod.

Usage : ./.venv/Scripts/python.exe -m app.research._exp_trend_daily
"""

import json

import httpx
import numpy as np
import pandas as pd

URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
    "?period1=946684800&period2=9999999999&interval=1d"
)
COST_BPS = 2.0          # coût par changement de position (turnover unit)
ANN = 252               # jours de bourse / an
FIN_BPS_PER_YEAR = 0.0  # financement CFD ignoré ici (voir note dans le rapport)


def load_gold() -> pd.DataFrame:
    headers = {"User-Agent": "Mozilla/5.0"}
    data = httpx.get(URL, headers=headers, timeout=30.0).json()
    r = data["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame(
        {"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"]},
        index=pd.to_datetime(r["timestamp"], unit="s").normalize(),
    )
    return df.dropna()


def metrics(strat_ret: pd.Series, position: pd.Series) -> dict:
    eq = (1 + strat_ret).cumprod()
    active = position != 0
    wins = strat_ret[active & (strat_ret > 0)]
    losses = strat_ret[active & (strat_ret < 0)]
    std = strat_ret.std()
    years = len(strat_ret) / ANN
    turn = position.diff().abs().fillna(position.abs())
    return {
        "sharpe": round(float(strat_ret.mean() / std * np.sqrt(ANN)), 2) if std > 0 else 0.0,
        "cagr_%": round(float((eq.iloc[-1] ** (1 / years) - 1) * 100), 1) if years > 0 else 0.0,
        "total_%": round(float((eq.iloc[-1] - 1) * 100), 1),
        "maxdd_%": round(float((eq / eq.cummax() - 1).min() * 100), 1),
        "pf": round(float(wins.sum() / abs(losses.sum())), 3) if losses.sum() != 0 else None,
        "expo_%": round(float(active.mean() * 100), 1),
        "trades": int((turn > 0).sum()),
    }


def run_rule(close, ret, signal: pd.Series, cost_bps: float) -> tuple[pd.Series, pd.Series]:
    """signal en {-1,0,1} calculé à la clôture t ; appliqué au rendement t+1 (causal)."""
    position = signal.shift(1).fillna(0)
    turn = position.diff().abs().fillna(position.abs())
    strat = position * ret - turn * (cost_bps / 1e4)
    return strat, position


def rules(df: pd.DataFrame) -> dict[str, pd.Series]:
    close, high, low = df["close"], df["high"], df["low"]
    out: dict[str, pd.Series] = {}

    # Time-series momentum : long si rendement passé N jours > 0
    for n in (50, 100, 200):
        mom = close.pct_change(n)
        out[f"TSMOM{n} L/F"] = (mom > 0).astype(float)
        out[f"TSMOM{n} L/S"] = np.sign(mom).replace(0, np.nan).ffill().fillna(0)

    # Croisement de moyennes mobiles
    for fast, slow in ((20, 100), (50, 200)):
        sig = (close.rolling(fast).mean() > close.rolling(slow).mean())
        out[f"MA{fast}/{slow} L/F"] = sig.astype(float)
        out[f"MA{fast}/{slow} L/S"] = np.where(sig, 1.0, -1.0)
        out[f"MA{fast}/{slow} L/S"] = pd.Series(out[f"MA{fast}/{slow} L/S"], index=close.index)

    # Donchian breakout (Turtle) : entrée > plus-haut N j antérieurs, sortie < plus-bas M j
    for n, m in ((20, 10), (55, 20)):
        hi = high.shift(1).rolling(n).max()
        lo = low.shift(1).rolling(m).min()
        pos = np.zeros(len(close))
        state = 0.0
        c = close.values
        hv, lv = hi.values, lo.values
        for i in range(len(c)):
            if state == 0.0 and not np.isnan(hv[i]) and c[i] > hv[i]:
                state = 1.0
            elif state == 1.0 and not np.isnan(lv[i]) and c[i] < lv[i]:
                state = 0.0
            pos[i] = state
        out[f"Donchian{n}/{m} L/F"] = pd.Series(pos, index=close.index)

    return out


def main() -> None:
    df = load_gold()
    close = df["close"]
    ret = close.pct_change().fillna(0)

    halves = {
        "full": df.index >= df.index[0],
        "h1_early": df.index < df.index[len(df) // 2],
        "h2_late": df.index >= df.index[len(df) // 2],
    }

    # Benchmark buy & hold
    bh_pos = pd.Series(1.0, index=close.index)
    bh_strat = bh_pos * ret

    report = {
        "data": {
            "points": int(len(df)),
            "start": str(df.index[0].date()),
            "end": str(df.index[-1].date()),
            "split_at": str(df.index[len(df) // 2].date()),
        },
        "note_financement": (
            "Coûts de transaction inclus (2 bps/turnover). Le financement CFD overnight "
            "(~portage, plusieurs %/an sur un long maintenu) N'EST PAS déduit — il pénalise "
            "surtout les stratégies à forte exposition longue, dont le buy&hold."
        ),
        "buy_and_hold": {k: metrics(bh_strat[m], bh_pos[m]) for k, m in halves.items()},
        "strategies": {},
    }

    for name, signal in rules(df).items():
        strat, position = run_rule(close, ret, signal, COST_BPS)
        report["strategies"][name] = {k: metrics(strat[m], position[m]) for k, m in halves.items()}

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
