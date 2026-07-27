"""Modèle de qualité de signal : P(objectif avant stop) pour un candidat sweep.

Contrat :
- la spécification des features (ordre, encodage, imputation) vit ICI et est
  partagée entre l'entraînement et l'inférence — pas de divergence possible ;
- le modèle est un ENSEMBLE de sous-modèles issus des folds walk-forward :
  la probabilité est la moyenne, l'incertitude est l'écart-type entre folds
  (désaccord des sous-modèles = données hors du domaine appris) ;
- l'inférence est SHADOW par défaut : elle enrichit le journal des décisions,
  elle ne bloque ni n'autorise rien tant que le gate n'est pas activé après
  validation.

Artefacts : models/liquidity_sweep/signal_quality/v<ts>/{model.joblib, meta.json}
Statut de tout nouvel artefact : CANDIDATE — jamais champion automatiquement.
"""

import json
import logging
import math
from datetime import datetime
from pathlib import Path

import joblib

logger = logging.getLogger("nexagold.ai.quality")

# Ordre canonique des features du modèle. Toute évolution = nouvelle version
# de FEATURE_SPEC_VERSION (les artefacts stockent la leur et refusent l'écart).
FEATURE_SPEC_VERSION = "sq_features_v1"
FEATURE_ORDER = (
    "sweep_depth_atr",
    "sweep_speed_bars",
    "sweep_rejection",
    "level_strength",
    "h1_atr_pct",
    "stop_loss_pct",
    "is_buy",
    "hour_sin",
    "hour_cos",
    "day_of_week",
    "source_m1",
)


def build_feature_vector(row: dict) -> list[float | None]:
    """dict (ligne de dataset OU features de signal live) -> vecteur ordonné.

    Les valeurs absentes restent None : l'imputation (médianes du TRAIN
    uniquement) est appliquée par le modèle, jamais ici.
    """
    hour = row.get("hour_utc")
    try:
        hour = float(hour) if hour is not None else None
    except (TypeError, ValueError):
        hour = None
    direction = str(row.get("direction") or "")

    def num(key):
        value = row.get(key)
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if math.isfinite(out) else None

    return [
        num("sweep_depth_atr"),
        num("sweep_speed_bars"),
        num("sweep_rejection"),
        num("level_strength"),
        num("h1_atr_pct"),
        num("stop_loss_pct"),
        1.0 if direction == "BUY" else 0.0,
        math.sin(2 * math.pi * hour / 24) if hour is not None else None,
        math.cos(2 * math.pi * hour / 24) if hour is not None else None,
        num("day_of_week"),
        1.0 if row.get("source_m1") in (1, 1.0, True, "1", "True") else 0.0,
    ]


class SignalQualityModel:
    """Ensemble chargé depuis un artefact versionné."""

    def __init__(self, models: list, medians: list[float], meta: dict):
        self._models = models
        self._medians = medians
        self.meta = meta
        self.version = meta.get("version", "unknown")

    @classmethod
    def load(cls, artifact_dir: Path) -> "SignalQualityModel | None":
        artifact_dir = Path(artifact_dir)
        model_path = artifact_dir / "model.joblib"
        meta_path = artifact_dir / "meta.json"
        if not model_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("feature_spec") != FEATURE_SPEC_VERSION:
                logger.warning(
                    "Artefact %s: spec de features %s incompatible avec %s — ignoré",
                    artifact_dir,
                    meta.get("feature_spec"),
                    FEATURE_SPEC_VERSION,
                )
                return None
            payload = joblib.load(model_path)
            return cls(payload["models"], payload["medians"], meta)
        except Exception:  # noqa: BLE001 — un artefact cassé ne doit pas tuer le moteur
            logger.exception("Chargement du modèle de qualité impossible (%s)", artifact_dir)
            return None

    @classmethod
    def load_latest(cls, base_dir: Path) -> "SignalQualityModel | None":
        base_dir = Path(base_dir)
        if not base_dir.exists():
            return None
        versions = sorted(
            (d for d in base_dir.iterdir() if d.is_dir() and d.name.startswith("v")),
            key=lambda d: d.name,
            reverse=True,
        )
        for directory in versions:
            model = cls.load(directory)
            if model is not None:
                return model
        return None

    def _impute(self, vector: list[float | None]) -> list[float]:
        return [
            v if v is not None else self._medians[i] for i, v in enumerate(vector)
        ]

    def evaluate(self, features: dict, when: datetime | None = None) -> dict:
        """P(objectif avant stop) + incertitude (désaccord entre folds)."""
        row = dict(features)
        if "hour_utc" not in row and when is not None:
            row["hour_utc"] = when.hour
            row["day_of_week"] = when.weekday()
        # L'inférence live vient du déclencheur M1 fidèle.
        row.setdefault("source_m1", 1.0)
        x = [self._impute(build_feature_vector(row))]
        probs = [float(m.predict_proba(x)[0][1]) for m in self._models]
        mean = sum(probs) / len(probs)
        variance = sum((p - mean) ** 2 for p in probs) / len(probs)
        return {
            "probability_target_before_stop": round(mean, 4),
            "uncertainty": round(math.sqrt(variance), 4),
            "fold_spread": [round(p, 4) for p in probs],
            "model_version": self.version,
            "feature_spec": FEATURE_SPEC_VERSION,
            "mode": "SHADOW",
        }
