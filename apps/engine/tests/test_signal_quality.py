"""Tests du contrat du modèle de qualité de signal (spec de features, garde-fous).

Le modèle v1 a été REJETÉ (aucun pouvoir prédictif) ; ces tests protègent le
CONTRAT réutilisable : ordre des features, absence de divergence
entraînement/inférence, refus d'un artefact incompatible ou absent.
"""

import json
from pathlib import Path

from app.ai.signal_quality import (
    FEATURE_ORDER,
    FEATURE_SPEC_VERSION,
    SignalQualityModel,
    build_feature_vector,
)


def test_feature_vector_matches_declared_order():
    vector = build_feature_vector(
        {
            "sweep_depth_atr": 0.5,
            "sweep_speed_bars": 1,
            "sweep_rejection": 0.8,
            "level_strength": 2,
            "h1_atr_pct": 0.004,
            "stop_loss_pct": 0.002,
            "direction": "BUY",
            "hour_utc": 6,
            "day_of_week": 2,
            "source_m1": 1,
        }
    )
    assert len(vector) == len(FEATURE_ORDER)
    assert vector[FEATURE_ORDER.index("is_buy")] == 1.0
    assert vector[FEATURE_ORDER.index("sweep_depth_atr")] == 0.5
    # 6h UTC -> sin(pi/2) = 1
    assert abs(vector[FEATURE_ORDER.index("hour_sin")] - 1.0) < 1e-9


def test_missing_and_invalid_values_stay_none_for_imputation():
    vector = build_feature_vector({"direction": "SELL", "sweep_depth_atr": "n/a"})
    assert vector[FEATURE_ORDER.index("sweep_depth_atr")] is None
    assert vector[FEATURE_ORDER.index("hour_sin")] is None
    assert vector[FEATURE_ORDER.index("is_buy")] == 0.0


def test_non_finite_values_are_rejected():
    vector = build_feature_vector({"direction": "BUY", "h1_atr_pct": float("nan")})
    assert vector[FEATURE_ORDER.index("h1_atr_pct")] is None


def test_load_returns_none_when_artifact_missing(tmp_path: Path):
    assert SignalQualityModel.load(tmp_path / "absent") is None
    assert SignalQualityModel.load_latest(tmp_path / "absent") is None


def test_load_refuses_incompatible_feature_spec(tmp_path: Path):
    artifact = tmp_path / "v1"
    artifact.mkdir()
    (artifact / "model.joblib").write_bytes(b"stub")
    (artifact / "meta.json").write_text(
        json.dumps({"version": "v1", "feature_spec": "ancienne_spec"}),
        encoding="utf-8",
    )
    # Spec différente => refus AVANT toute tentative de désérialisation.
    assert SignalQualityModel.load(artifact) is None
    assert FEATURE_SPEC_VERSION != "ancienne_spec"


def test_rejected_artifacts_are_marked_and_not_shadow_eligible():
    base = Path(__file__).resolve().parents[1] / "models" / "liquidity_sweep" / "signal_quality"
    if not base.exists():
        return  # artefacts hors git : rien à vérifier sur une machine vierge
    for directory in base.iterdir():
        meta_file = directory / "meta.json"
        if not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta.get("automatic_promotion") is False
        if meta.get("status") == "REJECTED":
            assert meta.get("eligible_for_shadow") is False
