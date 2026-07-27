"""Learning service: periodic retraining, manual promotion of the champion.

Gouvernance (audit 2026-07-27) : un réentraînement produit un CANDIDAT et ne
touche jamais au champion ni à la stratégie live. La promotion est une action
manuelle explicite (`promote()`), qui reste soumise au verrou paper-only du
Trader (`set_strategy` refuse d'échanger une stratégie paper contre une
stratégie non-paper).
"""

import asyncio
import logging
from pathlib import Path

from app.config import Settings
from app.execution.trader import Trader
from app.learning.registry import ModelRegistry
from app.learning.trainer import MODELS_DIR, retrain
from app.strategy.factory import build_strategy

logger = logging.getLogger("nexagold.learning")


class LearningService:
    def __init__(self, settings: Settings, trader: Trader):
        self._settings = settings
        self._trader = trader

    async def retrain_once(self) -> dict:
        result = await retrain(self._settings, self._settings.model_granularity)
        if "error" not in result:
            logger.info(
                "Candidat %s enregistré — promotion manuelle requise "
                "(champion actuel: %s)",
                result.get("candidate"),
                result.get("champion"),
            )
        return result

    def promote(self, version_id: str) -> dict:
        """Promotion MANUELLE d'une version en champion + rechargement live.

        Refuse une version inconnue ou sans artefact. Le rechargement de la
        stratégie passe par le verrou paper-only du Trader.
        """
        registry = ModelRegistry(
            Path(MODELS_DIR), self._settings.model_granularity
        )
        known = {v["id"] for v in registry.versions()}
        if version_id not in known:
            return {"promoted": False, "reason": f"Version inconnue: {version_id}"}
        if not (registry.version_dir(version_id) / "model.joblib").exists():
            return {
                "promoted": False,
                "reason": f"Artefact modèle absent pour {version_id}",
            }
        previous = registry.champion()
        registry.set_champion(version_id)
        self._trader.set_strategy(build_strategy(self._settings))
        logger.warning(
            "Promotion manuelle: champion %s -> %s", previous, version_id
        )
        return {
            "promoted": True,
            "champion": version_id,
            "previous_champion": previous,
            "rollback_hint": (
                f"POST /learning/promote?version={previous}" if previous else None
            ),
        }

    async def run_loop(self) -> None:
        interval = self._settings.learning_interval_seconds
        logger.info("Boucle d'apprentissage démarrée (intervalle=%ss)", interval)
        while True:
            try:
                result = await self.retrain_once()
                logger.info("Retrain: candidat=%s", result.get("candidate"))
            except Exception:  # noqa: BLE001 — the loop must never die silently
                logger.exception("Erreur inattendue pendant le réentraînement")
            await asyncio.sleep(interval)
