"""Génération du dataset d'entraînement du modèle de qualité de signal.

Rejoue une stratégie sur l'historique M1 en capturant TOUS les signaux
candidats (aucune contrainte de position : contrairement au backtest, un
signal émis pendant qu'un autre "trade" serait ouvert est quand même
capturé — le modèle doit apprendre sur tous les setups). Chaque candidat est :

1. dédupliqué par setup_id (un sweep ne compte qu'une fois, à sa première
   émission — les répétitions sur les bougies suivantes sont corrélées) ;
2. étiqueté par barrière (labels.label_signal) sur les bougies STRICTEMENT
   postérieures : TARGET_FIRST / STOP_FIRST / TIMEOUT / AMBIGUOUS (pessimiste)
   / INVALID_DATA ;
3. aplati en ligne de features numériques + métadonnées temporelles.

Sortie CSV — volontairement simple et versionnable par empreinte.

Usage :
  .venv\\Scripts\\python.exe -m app.learning.dataset_builder --days 180
  .venv\\Scripts\\python.exe -m app.learning.dataset_builder --days 1140 --base-granularity M5
"""

import argparse
import asyncio
import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.backtesting.engine import MultiTFWindows
from app.backtesting.run import build_strategy as build_sweep_strategy
from app.backtesting.run import load_base
from app.learning.labels import label_signal
from app.strategy.base import Action, Strategy

DATASETS_DIR = Path(__file__).resolve().parents[2] / "models" / "liquidity_sweep" / "datasets"

# Features numériques extraites du signal (absentes -> None).
FEATURE_KEYS = (
    "sweep_depth_atr",
    "sweep_speed_bars",
    "sweep_rejection",
    "level_strength",
    "h1_atr_pct",
    "stop_loss_pct",
    "risk_reward_ratio",
    "m5_atr",
    "shift_level",
    "sweep_level",
    "entry_reference",
)


def collect_candidates(
    strategy: Strategy,
    m1: list[dict],
    window_bars: int = 240,
    horizon_bars: int = 1440,
) -> list[dict]:
    """Tous les signaux candidats dédupliqués et étiquetés."""
    windows = MultiTFWindows(m1, strategy.extra_granularities, window_bars)
    seen_setups: set[str] = set()
    rows: list[dict] = []

    start = max(window_bars, 61)
    for i in range(start, len(m1)):
        bar = m1[i]
        bar_time = datetime.fromisoformat(bar["time"])
        extra = windows.extra_at(bar_time)
        m1_window = m1[max(0, i + 1 - window_bars) : i + 1]
        signal = strategy.evaluate(m1_window + [dict(m1_window[-1])], extra=extra)
        if signal.action == Action.HOLD:
            continue

        features = signal.features
        setup_id = str(features.get("setup_id") or f"anon:{bar['time']}")
        if setup_id in seen_setups:
            continue
        seen_setups.add(setup_id)

        direction = "BUY" if signal.action == Action.BUY else "SELL"
        stop_pct = float(features.get("stop_loss_pct") or 0.0)
        rr = float(features.get("risk_reward_ratio") or 0.0)
        label = label_signal(m1[i + 1 :], direction, stop_pct, rr, horizon_bars)

        row: dict = {
            "signal_time": bar["time"],
            "direction": direction,
            "confidence": round(float(signal.confidence), 4),
            "hour_utc": bar_time.hour,
            "day_of_week": bar_time.weekday(),
            "setup_id": setup_id,
        }
        for key in FEATURE_KEYS:
            value = features.get(key)
            try:
                row[key] = float(value) if value is not None else None
            except (TypeError, ValueError):
                row[key] = None
        row.update(
            {
                "outcome": label.outcome,
                "result_r": label.result_r,
                "bars_to_outcome": label.bars_to_outcome,
                "label_mfe_r": label.mfe_r,
                "label_mae_r": label.mae_r,
            }
        )
        rows.append(row)
    return rows


def write_dataset(rows: list[dict], name: str) -> Path:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    path = DATASETS_DIR / f"{name}.csv"
    if not rows:
        raise SystemExit("Aucun signal candidat — dataset vide, rien écrit")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


async def main() -> None:
    parser = argparse.ArgumentParser(description="Dataset qualité de signal")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--base-granularity", default="M1", choices=["M1", "M5"])
    parser.add_argument("--risk-reward", type=float, default=3.0)
    parser.add_argument("--window", type=int, default=240)
    parser.add_argument("--horizon-bars", type=int, default=1440)
    parser.add_argument("--sessions", default="LONDON,NEW_YORK")
    parser.add_argument("--no-sessions", action="store_true")
    parser.add_argument("--no-retest", action="store_true")
    args = parser.parse_args()

    m1 = await load_base(args.days, args.base_granularity)
    if len(m1) < 2000:
        raise SystemExit(f"Seulement {len(m1)} bougies en base")
    print(f"{len(m1)} bougies {args.base_granularity}")

    strategy = build_sweep_strategy(args)
    horizon = args.horizon_bars if args.base_granularity == "M1" else 288
    rows = collect_candidates(strategy, m1, args.window, horizon)

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    name = f"sweep_{args.days}d_{args.base_granularity}_rr{args.risk_reward:g}_{stamp}"
    path = write_dataset(rows, name)

    outcomes = Counter(r["outcome"] for r in rows)
    usable = [r for r in rows if r["outcome"] in ("TARGET_FIRST", "STOP_FIRST", "AMBIGUOUS")]
    hits = sum(1 for r in usable if r["outcome"] == "TARGET_FIRST")
    print(f"\n{len(rows)} signaux candidats -> {path}")
    print("Répartition:", dict(outcomes))
    if usable:
        print(
            f"P(TARGET_FIRST | tranché) = {hits}/{len(usable)} "
            f"= {hits / len(usable):.3f}"
        )
        rs = [r["result_r"] for r in usable if r["result_r"] is not None]
        if rs:
            print(f"Espérance brute (hors coûts) = {sum(rs) / len(rs):+.4f}R")


if __name__ == "__main__":
    asyncio.run(main())
