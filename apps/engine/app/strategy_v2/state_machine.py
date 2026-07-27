"""Machine à états du cycle de vie d'un setup LIQUIDITY_SWEEP.

Chaque évaluation de la stratégie fait progresser (ou rejette) un setup à
travers des états explicites. Toutes les transitions sont horodatées, motivées
et historisées ; une transition interdite lève une erreur contrôlée
(`ForbiddenTransition`) au lieu de laisser passer une exécution.

Les états d'exécution (AI_EVALUATION → POSITION_*) appartiennent au Trader et
au RiskManager dans ce moteur ; la machine matérialise ici la partie
stratégie : contexte → zone → sweep → réintégration → shift → retest → prêt.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("nexagold.sweep.fsm")

IDLE = "IDLE"
CONTEXT_VALIDATED = "CONTEXT_VALIDATED"
ZONE_DETECTED = "ZONE_DETECTED"
SWEEP_DETECTED = "SWEEP_DETECTED"
REINTEGRATION_CONFIRMED = "REINTEGRATION_CONFIRMED"
STRUCTURE_SHIFT_CONFIRMED = "STRUCTURE_SHIFT_CONFIRMED"
WAITING_RETEST = "WAITING_RETEST"
READY_TO_EXECUTE = "READY_TO_EXECUTE"
REJECTED = "REJECTED"
COOLDOWN = "COOLDOWN"
SYSTEM_LOCKED = "SYSTEM_LOCKED"

STATES = (
    IDLE,
    CONTEXT_VALIDATED,
    ZONE_DETECTED,
    SWEEP_DETECTED,
    REINTEGRATION_CONFIRMED,
    STRUCTURE_SHIFT_CONFIRMED,
    WAITING_RETEST,
    READY_TO_EXECUTE,
    REJECTED,
    COOLDOWN,
    SYSTEM_LOCKED,
)

# Progression nominale + sorties permises. REJECTED/COOLDOWN/SYSTEM_LOCKED
# sont accessibles depuis tout état actif ; IDLE n'est rejoint que par reset().
_FORWARD = {
    IDLE: {CONTEXT_VALIDATED},
    CONTEXT_VALIDATED: {ZONE_DETECTED},
    ZONE_DETECTED: {SWEEP_DETECTED},
    SWEEP_DETECTED: {REINTEGRATION_CONFIRMED},
    REINTEGRATION_CONFIRMED: {STRUCTURE_SHIFT_CONFIRMED},
    STRUCTURE_SHIFT_CONFIRMED: {WAITING_RETEST, READY_TO_EXECUTE},
    WAITING_RETEST: {READY_TO_EXECUTE},
    READY_TO_EXECUTE: set(),
    REJECTED: set(),
    COOLDOWN: set(),
    SYSTEM_LOCKED: set(),
}
_EXITS = {REJECTED, COOLDOWN, SYSTEM_LOCKED}
_MAX_HISTORY = 300


class ForbiddenTransition(RuntimeError):
    """Transition non autorisée — le setup est invalide, pas exécutable."""


class SetupStateMachine:
    def __init__(self, state_path: Path | None = None):
        self._path = Path(state_path) if state_path else None
        self.state = IDLE
        self.history: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self.history = list(data.get("history") or [])[-_MAX_HISTORY:]
            # L'état courant n'est PAS restauré : chaque redémarrage repart
            # d'IDLE (le marché a bougé), seul l'historique est conservé.
        except (OSError, ValueError) as exc:
            logger.warning("Historique FSM illisible (%s) — historique vierge", exc)

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {"history": self.history[-_MAX_HISTORY:]}, ensure_ascii=False
                ),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError as exc:
            logger.warning("Impossible de persister l'historique FSM: %s", exc)

    def to(self, state: str, reason: str, now: datetime | None = None) -> None:
        """Transition contrôlée. Interdite => ForbiddenTransition (pas d'ordre)."""
        if state not in STATES:
            raise ForbiddenTransition(f"État inconnu: {state}")
        allowed = state in _FORWARD.get(self.state, set()) or (
            state in _EXITS and self.state not in _EXITS
        )
        if not allowed:
            raise ForbiddenTransition(
                f"Transition interdite: {self.state} -> {state} ({reason})"
            )
        entry = {
            "from": self.state,
            "to": state,
            "reason": reason,
            "at": (now or datetime.now(timezone.utc)).isoformat(),
        }
        self.state = state
        self.history.append(entry)
        self.history = self.history[-_MAX_HISTORY:]
        self._save()

    def reset(self, reason: str, now: datetime | None = None) -> None:
        """Retour à IDLE (fin de cycle d'évaluation), toujours permis."""
        if self.state == IDLE:
            return
        entry = {
            "from": self.state,
            "to": IDLE,
            "reason": reason,
            "at": (now or datetime.now(timezone.utc)).isoformat(),
        }
        self.state = IDLE
        self.history.append(entry)
        self.history = self.history[-_MAX_HISTORY:]
        self._save()

    def status(self) -> dict:
        return {
            "state": self.state,
            "recent_transitions": self.history[-15:],
            "state_path": str(self._path) if self._path else None,
        }
