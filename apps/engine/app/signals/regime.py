"""Market regime classification v1.

This is intentionally simple, deterministic and explainable. It classifies the
current context from compact math features, and should later be replaced or
augmented by a validated statistical regime model.
"""

from dataclasses import asdict, dataclass


@dataclass
class MarketRegime:
    regime: str
    trend: str
    volatility: str
    confidence: float
    reasons: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RegimeGate:
    allowed: bool
    status: str
    agreement: str
    reasons: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def assess_regime_gate(
    direction: str,
    regime_details: dict | None,
    math_summary: dict | None,
) -> dict:
    """Decide whether a directional preview is compatible with its regime.

    This gate only enriches the read-only structured signal. The live trading
    path keeps its existing strategy and risk-manager behavior.
    """
    direction = direction.upper()
    if direction not in {"BUY", "SELL"}:
        return RegimeGate(
            allowed=False,
            status="NOT_APPLICABLE",
            agreement="NEUTRAL",
            reasons=["Aucun signal directionnel à évaluer"],
            warnings=[],
        ).to_dict()

    regime_details = regime_details or {}
    math_summary = math_summary or {}
    reasons: list[str] = []
    warnings: list[str] = []
    blocked = False

    quality = _optional_float(math_summary.get("data_quality_score")) or 0.0
    regime = str(regime_details.get("regime") or "UNKNOWN")
    trend = str(regime_details.get("trend") or "UNKNOWN")
    volatility = str(regime_details.get("volatility") or "UNKNOWN")
    confidence = _optional_float(regime_details.get("confidence")) or 0.0

    if quality < 0.8 or regime == "LOW_DATA_QUALITY":
        blocked = True
        reasons.append("Qualité des données insuffisante")

    vol_ratio = _optional_float(math_summary.get("volatility_ratio_5_20"))
    atr_pct = _optional_float(math_summary.get("atr_pct_14"))
    extreme_volatility = (vol_ratio is not None and vol_ratio >= 2.2) or (
        atr_pct is not None and atr_pct >= 0.02
    )
    if extreme_volatility:
        blocked = True
        reasons.append("Volatilité extrême incompatible avec ce signal")
        warnings.append("Filtre régime : volatilité extrême détectée")
    elif volatility == "HIGH_VOLATILITY":
        warnings.append("Régime de forte volatilité : exécution à surveiller")

    expected_trend = "BULLISH" if direction == "BUY" else "BEARISH"
    opposite_trend = "BEARISH" if direction == "BUY" else "BULLISH"
    if trend == expected_trend:
        agreement = "ALIGNED"
        reasons.append(f"Signal {direction} aligné avec le régime {trend}")
    elif trend == opposite_trend:
        agreement = "CONFLICT"
        if confidence >= 0.45:
            blocked = True
            reasons.append(
                f"Signal {direction} en contradiction forte avec le régime {trend}"
            )
        else:
            warnings.append(
                f"Signal {direction} en contradiction avec un régime peu fiable"
            )
    elif trend == "RANGE":
        agreement = "NEUTRAL"
        warnings.append("Régime latéral : avantage directionnel non confirmé")
    else:
        agreement = "UNKNOWN"
        warnings.append("Compatibilité modèle/régime indéterminée")

    return RegimeGate(
        allowed=not blocked,
        status="BLOCKED" if blocked else "ALLOWED",
        agreement=agreement,
        reasons=reasons,
        warnings=warnings,
    ).to_dict()


def classify_regime(math_summary: dict | None) -> dict:
    if not math_summary:
        return MarketRegime(
            regime="UNKNOWN",
            trend="UNKNOWN",
            volatility="UNKNOWN",
            confidence=0.0,
            reasons=[],
            warnings=["Résumé mathématique indisponible"],
        ).to_dict()

    quality = float(math_summary.get("data_quality_score") or 0)
    warnings = list(math_summary.get("warnings") or [])
    reasons: list[str] = []

    if quality < 0.6:
        return MarketRegime(
            regime="LOW_DATA_QUALITY",
            trend="UNKNOWN",
            volatility="UNKNOWN",
            confidence=round(quality, 3),
            reasons=["Qualité des données insuffisante pour classifier le régime"],
            warnings=warnings,
        ).to_dict()

    momentum_12 = math_summary.get("momentum_12")
    slope = math_summary.get("trend_strength")
    zscore = math_summary.get("zscore_20")
    vol_ratio = math_summary.get("volatility_ratio_5_20")
    atr_pct = math_summary.get("atr_pct_14")

    trend = "RANGE"
    trend_score = 0.0
    if momentum_12 is not None and slope is not None:
        if momentum_12 > 0.003 and slope > 0:
            trend = "BULLISH"
            trend_score = min(abs(momentum_12) * 50, 1.0)
            reasons.append("Momentum 12 positif et pente positive")
        elif momentum_12 < -0.003 and slope < 0:
            trend = "BEARISH"
            trend_score = min(abs(momentum_12) * 50, 1.0)
            reasons.append("Momentum 12 négatif et pente négative")
        elif zscore is not None and abs(zscore) < 0.7:
            reasons.append("Prix proche de sa moyenne récente")
    else:
        trend = "UNKNOWN"
        warnings.append("Tendance indéterminée : momentum ou pente indisponible")

    volatility = "NORMAL_VOLATILITY"
    vol_score = 0.5
    if vol_ratio is not None:
        if vol_ratio >= 1.6:
            volatility = "HIGH_VOLATILITY"
            vol_score = min(vol_ratio / 2.5, 1.0)
            reasons.append("Volatilité courte supérieure au régime récent")
        elif vol_ratio <= 0.6:
            volatility = "LOW_VOLATILITY"
            vol_score = min((0.6 - vol_ratio) / 0.6, 1.0)
            reasons.append("Contraction de volatilité")
    elif atr_pct is not None:
        if atr_pct >= 0.01:
            volatility = "HIGH_VOLATILITY"
            vol_score = min(atr_pct / 0.02, 1.0)
            reasons.append("ATR élevé relativement au prix")
    else:
        volatility = "UNKNOWN_VOLATILITY"
        warnings.append("Volatilité indéterminée")

    if volatility == "HIGH_VOLATILITY":
        regime = f"{trend}_HIGH_VOLATILITY" if trend != "UNKNOWN" else "HIGH_VOLATILITY"
    elif trend == "BULLISH":
        regime = "BULLISH_TREND"
    elif trend == "BEARISH":
        regime = "BEARISH_TREND"
    elif trend == "RANGE":
        regime = "RANGE"
    else:
        regime = "UNKNOWN"

    confidence = round(max(0.0, min(quality * max(trend_score, vol_score), 1.0)), 3)
    if not reasons:
        reasons.append("Aucun signal de régime dominant")

    return MarketRegime(
        regime=regime,
        trend=trend,
        volatility=volatility,
        confidence=confidence,
        reasons=reasons,
        warnings=warnings,
    ).to_dict()
