"""Kill switch dynamique et persistant.

Contrairement au kill switch statique TRADING_ENABLED (variable d'environnement,
redémarrage requis), ce verrou peut être posé À CHAUD par le moteur de risque
(perte quotidienne/hebdomadaire atteinte, série de pertes) ou par l'opérateur
(endpoint /risk/lock), et il survit à un redémarrage via un fichier d'état JSON.

Règles :
- verrouillé => aucun NOUVEL ordre d'ouverture ; les clôtures (prise de profit,
  sortie d'horizon, réconciliation) restent autorisées car elles RÉDUISENT le
  risque ;
- la réactivation exige une action explicite avec une raison (jamais
  automatique, jamais décidée par un modèle) ;
- chaque verrouillage/déverrouillage est horodaté et journalisé avec sa cause.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("nexagold.killswitch")

_MAX_HISTORY = 100


class KillSwitch:
    def __init__(self, state_path: Path):
        self._path = Path(state_path)
        self._locked = False
        self._reason: str | None = None
        self._locked_at: str | None = None
        self._source: str | None = None
        self._history: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            state = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Etat illisible : on repart VERROUILLÉ par prudence — un fichier
            # corrompu ne doit jamais se traduire par « tout est permis ».
            logger.error("État du kill switch illisible (%s) — verrouillage préventif", exc)
            self._locked = True
            self._reason = "État du kill switch illisible au démarrage"
            self._locked_at = datetime.now(timezone.utc).isoformat()
            self._source = "system"
            return
        self._locked = bool(state.get("locked"))
        self._reason = state.get("reason")
        self._locked_at = state.get("locked_at")
        self._source = state.get("source")
        self._history = list(state.get("history") or [])[-_MAX_HISTORY:]

    def _save(self) -> None:
        payload = {
            "locked": self._locked,
            "reason": self._reason,
            "locked_at": self._locked_at,
            "source": self._source,
            "history": self._history[-_MAX_HISTORY:],
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self._path)
        except OSError as exc:
            logger.error("Impossible de persister l'état du kill switch: %s", exc)

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def reason(self) -> str | None:
        return self._reason

    def lock(self, reason: str, source: str = "auto") -> dict:
        """Pose le verrou (idempotent). `source` : auto | operator | system."""
        event = {
            "event": "LOCK",
            "reason": reason,
            "source": source,
            "at": datetime.now(timezone.utc).isoformat(),
            "already_locked": self._locked,
        }
        if not self._locked:
            self._locked = True
            self._reason = reason
            self._locked_at = event["at"]
            self._source = source
            logger.critical("KILL SWITCH VERROUILLÉ (%s): %s", source, reason)
        self._history.append(event)
        self._save()
        return self.status()

    def unlock(self, reason: str, source: str = "operator") -> dict:
        """Lève le verrou. Une raison explicite est OBLIGATOIRE (audit trail).

        Seul un opérateur (ou un test) appelle ceci — jamais une boucle
        automatique, jamais un modèle.
        """
        if not reason or not reason.strip():
            raise ValueError("Une raison explicite est requise pour déverrouiller")
        event = {
            "event": "UNLOCK",
            "reason": reason.strip(),
            "source": source,
            "at": datetime.now(timezone.utc).isoformat(),
            "was_locked": self._locked,
        }
        self._locked = False
        self._reason = None
        self._locked_at = None
        self._source = None
        self._history.append(event)
        self._save()
        logger.warning("Kill switch déverrouillé (%s): %s", source, reason)
        return self.status()

    def status(self) -> dict:
        return {
            "locked": self._locked,
            "reason": self._reason,
            "locked_at": self._locked_at,
            "source": self._source,
            "recent_events": self._history[-10:],
            "state_path": str(self._path),
        }
