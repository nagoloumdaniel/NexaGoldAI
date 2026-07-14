"""Strategy selection.

Loads the trained LightGBM model if it exists, otherwise falls back to the
AlwaysHold placeholder so the engine always has a working strategy.
"""

import logging
from pathlib import Path

from app.config import Settings
from app.learning.registry import ModelRegistry
from app.strategy.base import AlwaysHold, Strategy
from app.strategy.expected_return_strategy import ExpectedReturnPaperStrategy
from app.strategy.lightgbm_strategy import LightGBMStrategy

logger = logging.getLogger("nexagold.strategy")

_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def build_strategy(settings: Settings) -> Strategy:
    if settings.strategy_name == "expected_return_paper":
        if settings.capital_env != "demo":
            raise RuntimeError(
                "expected_return_paper est strictement interdit hors CAPITAL_ENV=demo"
            )
        paper_dir = (
            _MODELS_DIR / settings.model_granularity / "expected_return_paper"
        )
        if (paper_dir / "model.joblib").exists() and (paper_dir / "meta.json").exists():
            logger.info("Strategie expected-return PAPER chargee depuis %s", paper_dir)
            return ExpectedReturnPaperStrategy(paper_dir, settings.model_granularity)
        logger.warning("Artefact expected-return paper absent - repli sur AlwaysHold")
        return AlwaysHold()
    if settings.strategy_name == "lightgbm":
        # Prefer the registry champion (phase 5); fall back to a flat model
        # dir (phase 2 CLI output) for backward compatibility.
        champion = ModelRegistry(_MODELS_DIR, settings.model_granularity).champion_dir()
        if champion is not None:
            logger.info("Stratégie LightGBM (champion) chargée depuis %s", champion)
            return LightGBMStrategy(champion)
        legacy = _MODELS_DIR / settings.model_granularity
        if (legacy / "model.joblib").exists():
            logger.info("Stratégie LightGBM (modèle simple) chargée depuis %s", legacy)
            return LightGBMStrategy(legacy)
        logger.warning("Aucun modèle LightGBM trouvé — repli sur AlwaysHold")
    return AlwaysHold()
