"""Backtest CLI: load candles, run walk-forward, train + save the final model.

Usage:
  .venv\\Scripts\\python.exe -m app.research.run --granularity M5 \
      --labeling triple_barrier --horizon 24 --vol-mult 1.5 --folds 5

Writes models/<granularity>/model.joblib, meta.json and report.json.
"""

import argparse
import asyncio
import json
from pathlib import Path

import joblib

from app.config import get_settings
from app.research import backtest as bt
from app.research.dataset import load_candles
from app.research.features import feature_columns

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def main() -> None:
    parser = argparse.ArgumentParser(description="NexaGold walk-forward backtest")
    parser.add_argument("--granularity", default="M5")
    parser.add_argument(
        "--labeling", choices=["fixed", "triple_barrier"], default="fixed"
    )
    parser.add_argument("--horizon", type=int, default=12)
    parser.add_argument("--threshold", type=float, default=0.001)
    parser.add_argument("--vol-mult", type=float, default=1.0)
    parser.add_argument("--vol-window", type=int, default=20)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--cost-bps", type=float, default=2.0)
    args = parser.parse_args()

    config = {
        "labeling": args.labeling,
        "horizon": args.horizon,
        "threshold": args.threshold,
        "vol_mult": args.vol_mult,
        "vol_window": args.vol_window,
    }

    settings = get_settings()
    df = asyncio.run(load_candles(settings, args.granularity))
    if df.empty or len(df) < 500:
        print(json.dumps({"error": f"Données insuffisantes ({len(df)} bougies)"}))
        return

    data = bt.build_dataset(df, config)
    feature_cols = feature_columns(data)
    report = bt.run(
        data, feature_cols, args.folds, args.granularity, cost_bps=args.cost_bps
    )
    report["params"] = {
        "granularity": args.granularity,
        "config": config,
        "folds": args.folds,
        "cost_bps": args.cost_bps,
        "candles": int(len(df)),
        "range": [str(df.index[0]), str(df.index[-1])],
    }

    # Final model trained on ALL data, for live use by LightGBMStrategy.
    final_model = bt.make_model()
    final_model.fit(data[feature_cols], data["label"].astype(int).values)

    out_dir = MODELS_DIR / args.granularity
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(final_model, out_dir / "model.joblib")
    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "feature_cols": feature_cols,
                "config": config,
                "granularity": args.granularity,
                "confidence_threshold": report["best_confidence_threshold"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nModèle et rapport enregistrés dans {out_dir}")


if __name__ == "__main__":
    main()
