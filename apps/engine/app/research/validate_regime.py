"""Read-only CLI for held-out validation of the market-regime gate.

Usage:
  .venv/Scripts/python.exe -m app.research.validate_regime --granularity H1
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.research import backtest as bt
from app.research.dataset import load_candles
from app.research.features import feature_columns

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validation read-only du filtre regime")
    parser.add_argument("--granularity", default="H1")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--cost-bps", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    model_dir = MODELS_DIR / args.granularity
    meta = _read_json(model_dir / "meta.json")
    previous_report = _read_json(model_dir / "report.json")
    config = meta.get("config") or {
        "labeling": "fixed",
        "horizon": 24,
        "threshold": 0.002,
    }
    cost_bps = args.cost_bps
    if cost_bps is None:
        cost_bps = float(previous_report.get("params", {}).get("cost_bps", 2.0))

    settings = get_settings()
    candles = asyncio.run(load_candles(settings, args.granularity))
    if candles.empty or len(candles) < 500:
        print(json.dumps({"error": f"Donnees insuffisantes ({len(candles)} bougies)"}))
        return

    data = bt.build_dataset(candles, config)
    report = bt.run(
        data,
        feature_columns(data),
        args.folds,
        args.granularity,
        cost_bps=cost_bps,
        embargo=int(config.get("horizon", 0)),
    )
    result = {
        "params": {
            "granularity": args.granularity,
            "config": config,
            "folds": args.folds,
            "cost_bps": cost_bps,
            "candles": int(len(candles)),
            "range": [str(candles.index[0]), str(candles.index[-1])],
        },
        "samples": report["samples"],
        "evaluated": report["evaluated"],
        "accuracy": report["accuracy"],
        "f1_macro": report["f1_macro"],
        "regime_gate_validation": report["regime_gate_validation"],
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
