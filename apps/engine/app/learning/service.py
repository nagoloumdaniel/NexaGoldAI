"""Learning service: periodic retraining + hot-swap of the live strategy.

When a retrain promotes a new champion, the running Trader is handed a freshly
built strategy so the next decision uses the updated model — no restart.
"""

import asyncio
import logging

from app.config import Settings
from app.execution.trader import Trader
from app.learning.trainer import retrain
from app.strategy.factory import build_strategy

logger = logging.getLogger("nexagold.learning")


class LearningService:
    def __init__(self, settings: Settings, trader: Trader):
        self._settings = settings
        self._trader = trader

    async def retrain_once(self) -> dict:
        result = await retrain(self._settings, self._settings.model_granularity)
        if "error" not in result:
            self._trader.set_strategy(build_strategy(self._settings))
            logger.info("Stratégie rechargée sur le champion %s", result["champion"])
        return result

    async def run_loop(self) -> None:
        interval = self._settings.learning_interval_seconds
        logger.info("Boucle d'apprentissage démarrée (intervalle=%ss)", interval)
        while True:
            try:
                result = await self.retrain_once()
                logger.info("Retrain: champion=%s", result.get("champion"))
            except Exception:  # noqa: BLE001 — the loop must never die silently
                logger.exception("Erreur inattendue pendant le réentraînement")
            await asyncio.sleep(interval)
