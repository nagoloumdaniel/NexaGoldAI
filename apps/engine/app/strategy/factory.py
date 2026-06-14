"""Strategy selection.

Loads the trained LightGBM model if it exists, otherwise falls back to the
AlwaysHold placeholder so the engine always has a working strategy.
"""

import logging
from pathlib import Path

from app.config import Settings
from app.strategy.base import AlwaysHold, Strategy
from app.strategy.lightgbm_strategy import LightGBMStrategy

logger = logging.getLogger("nexagold.strategy")

_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def build_strategy(settings: Settings) -> Strategy:
    if settings.strategy_name == "lightgbm":
        model_dir = _MODELS_DIR / settings.model_granularity
        if (model_dir / "model.joblib").exists():
            logger.info("Stratégie LightGBM chargée depuis %s", model_dir)
            return LightGBMStrategy(model_dir)
        logger.warning(
            "Modèle LightGBM introuvable (%s) — repli sur AlwaysHold", model_dir
        )
    return AlwaysHold()
