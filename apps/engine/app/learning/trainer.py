"""Retraining round: several candidate configs compete, the best is promoted.

Each round re-evaluates every candidate on the LATEST data via walk-forward, so
selection always reflects current market conditions. The winner is trained on
all data, registered as a new version and made champion.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import joblib

from app.config import Settings
from app.learning.registry import ModelRegistry
from app.research import backtest as bt
from app.research.dataset import load_candles
from app.research.features import feature_columns

logger = logging.getLogger("nexagold.learning")

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"

# Search space — different labelling horizons/thresholds = different "approaches".
CANDIDATE_CONFIGS = [
    {"horizon": 12, "threshold": 0.0010},
    {"horizon": 12, "threshold": 0.0015},
    {"horizon": 24, "threshold": 0.0020},
]


def _selection_metric(report: dict) -> float:
    # Out-of-sample annualised Sharpe of the PnL backtest. Higher is better;
    # may be negative (then we pick the least-bad, honestly).
    return report["pnl"]["sharpe_annualised"]


async def retrain(settings: Settings, granularity: str, folds: int = 5) -> dict:
    df = await load_candles(settings, granularity)
    if df.empty or len(df) < 500:
        return {"error": f"Données insuffisantes ({len(df)} bougies)"}

    registry = ModelRegistry(MODELS_DIR, granularity)

    leaderboard = []
    for config in CANDIDATE_CONFIGS:
        data = bt.build_dataset(df, config["horizon"], config["threshold"])
        cols = feature_columns(data)
        report = bt.run(data, cols, folds, granularity)
        leaderboard.append(
            {
                "config": config,
                "metric": _selection_metric(report),
                "report": report,
                "data": data,
                "cols": cols,
            }
        )

    leaderboard.sort(key=lambda entry: entry["metric"], reverse=True)
    best = leaderboard[0]

    version_id = "v" + datetime.now().strftime("%Y%m%d%H%M%S")
    version_dir = registry.version_dir(version_id)
    version_dir.mkdir(parents=True, exist_ok=True)

    model = bt.make_model()
    model.fit(best["data"][best["cols"]], best["data"]["label"].astype(int).values)
    joblib.dump(model, version_dir / "model.joblib")
    (version_dir / "meta.json").write_text(
        json.dumps(
            {
                "feature_cols": best["cols"],
                "horizon": best["config"]["horizon"],
                "threshold": best["config"]["threshold"],
                "granularity": granularity,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (version_dir / "report.json").write_text(
        json.dumps(best["report"], indent=2), encoding="utf-8"
    )

    registry.add_version(
        version_id,
        best["config"],
        {
            "selection_metric": "sharpe_annualised",
            "value": best["metric"],
            "accuracy": best["report"]["accuracy"],
            "sharpe": best["report"]["pnl"]["sharpe_annualised"],
            "profit_factor": best["report"]["pnl"]["profit_factor"],
            "samples": best["report"]["samples"],
        },
        make_champion=True,
    )

    summary = {
        "champion": version_id,
        "selected_config": best["config"],
        "candles": int(len(df)),
        "leaderboard": [
            {
                "config": entry["config"],
                "sharpe": entry["report"]["pnl"]["sharpe_annualised"],
                "accuracy": entry["report"]["accuracy"],
            }
            for entry in leaderboard
        ],
    }
    logger.info("Retrain terminé: %s", summary["selected_config"])
    return summary
