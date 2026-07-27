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

# Search space — each entry is a different "approach" (labelling, horizon,
# volatility, with/without macro). They compete head to head every round.
CANDIDATE_CONFIGS = [
    {"labeling": "triple_barrier", "horizon": 12, "vol_mult": 1.0, "vol_window": 20},
    {"labeling": "triple_barrier", "horizon": 24, "vol_mult": 1.5, "vol_window": 20},
    {"labeling": "triple_barrier", "horizon": 48, "vol_mult": 2.0, "vol_window": 50},
    {"labeling": "fixed", "horizon": 12, "threshold": 0.0010},
    {"labeling": "fixed", "horizon": 24, "threshold": 0.0020},
    {"labeling": "fixed", "horizon": 24, "threshold": 0.0020, "macro": True},
    {
        "labeling": "triple_barrier",
        "horizon": 24,
        "vol_mult": 1.5,
        "vol_window": 20,
        "macro": True,
    },
]


def _selection_metric(report: dict) -> float:
    # Out-of-sample annualised Sharpe of the PnL backtest. Higher is better;
    # may be negative (then we pick the least-bad, honestly).
    return report["pnl"]["sharpe_annualised"]


async def retrain(
    settings: Settings, granularity: str, folds: int = 5, promote: bool = False
) -> dict:
    """Entraîne les candidats et enregistre le meilleur comme CANDIDAT.

    `promote=False` par défaut (gouvernance 2026-07-27) : un réentraînement ne
    change plus jamais le champion tout seul — la promotion est une action
    manuelle explicite (POST /learning/promote), jamais déclenchée par la
    boucle d'apprentissage.
    """
    df = await load_candles(settings, granularity)
    if df.empty or len(df) < 500:
        return {"error": f"Données insuffisantes ({len(df)} bougies)"}

    registry = ModelRegistry(MODELS_DIR, granularity)

    # Load the macro series once if any candidate needs it; drop macro configs
    # if no macro data is available yet.
    configs = list(CANDIDATE_CONFIGS)
    macro_df = None
    if any(c.get("macro") for c in configs):
        macro_df = await load_candles(
            settings, granularity, instrument=settings.macro_instrument
        )
        if macro_df is None or macro_df.empty:
            configs = [c for c in configs if not c.get("macro")]

    leaderboard = []
    for config in configs:
        data = bt.build_dataset(df, config, macro_df)
        cols = feature_columns(data)
        report = bt.run(data, cols, folds, granularity, embargo=config["horizon"])
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
                "config": best["config"],
                "granularity": granularity,
                "confidence_threshold": best["report"]["best_confidence_threshold"],
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
            "confidence_threshold": best["report"]["best_confidence_threshold"],
            "samples": best["report"]["samples"],
        },
        make_champion=promote,
    )

    summary = {
        "candidate": version_id,
        "champion": registry.champion(),
        "promotion_required": not promote,
        "selected_config": best["config"],
        "confidence_threshold": best["report"]["best_confidence_threshold"],
        "candles": int(len(df)),
        "leaderboard": [
            {
                "config": entry["config"],
                "sharpe": entry["report"]["pnl"]["sharpe_annualised"],
                "accuracy": entry["report"]["accuracy"],
                "confidence_threshold": entry["report"]["best_confidence_threshold"],
            }
            for entry in leaderboard
        ],
    }
    logger.info("Retrain terminé: %s", summary["selected_config"])
    return summary
