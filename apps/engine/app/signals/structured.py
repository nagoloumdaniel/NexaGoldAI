"""Structured trading signal contract.

This is the public, explainable decision shape consumed by API/dashboard.
It wraps the existing strategy signal without pretending that calibration,
market regime or expected value are fully implemented yet.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import isnan
from typing import Any

from app.config import Settings
from app.signals.math_features import build_math_summary
from app.signals.regime import assess_regime_gate, classify_regime
from app.strategy.base import Action, Signal


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if isnan(out) else out


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _bracket(
    action: Action, entry: float, stop_loss_pct: float, risk_reward: float
) -> tuple[float, float]:
    if action == Action.BUY:
        return entry * (1 - stop_loss_pct), entry * (1 + stop_loss_pct * risk_reward)
    return entry * (1 + stop_loss_pct), entry * (1 - stop_loss_pct * risk_reward)


@dataclass
class StructuredSignal:
    symbol: str
    timestamp: str
    timeframe: str
    direction: str
    probability_up: float
    probability_down: float
    probability_neutral: float
    raw_model_score: float
    calibrated_confidence: float
    uncertainty: float
    data_quality_score: float
    market_regime: str
    expected_move: float | None
    expected_value_after_costs: float | None
    spread: float | None
    slippage_estimate: float | None
    recommended_entry: float | None
    recommended_sl: float | None
    recommended_tp: float | None
    risk_reward_ratio: float | None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model_version: str | None = None
    execution_mode: str = "DEMO"
    math_summary: dict | None = None
    regime_details: dict | None = None
    regime_gate: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def candle_quality(candles: list[dict], min_count: int) -> tuple[float, list[str]]:
    warnings: list[str] = []
    if not candles:
        return 0.0, ["Aucune bougie disponible"]

    count_score = min(len(candles) / max(min_count, 1), 1.0)
    latest = _parse_time(candles[-1].get("time"))
    stale_score = 1.0
    if latest is None:
        warnings.append("Timestamp de derniere bougie illisible")
        stale_score = 0.5
    else:
        age_seconds = (datetime.now(timezone.utc) - latest).total_seconds()
        # Conservative generic stale threshold. A regime-specific data-quality
        # engine will replace this once multi-timeframe support is introduced.
        if age_seconds > 3 * 3600:
            warnings.append("Donnees potentiellement trop anciennes")
            stale_score = 0.5

    if count_score < 1.0:
        warnings.append("Historique recent insuffisant pour le modele")
    return round(min(count_score, stale_score), 3), warnings


def build_structured_signal(
    settings: Settings,
    strategy_name: str,
    signal: Signal,
    candles: list[dict],
    price: dict | None,
    model_version: str | None,
) -> dict:
    quality, warnings = candle_quality(candles, settings.decision_candles)
    math_summary = build_math_summary(candles, min_count=min(settings.decision_candles, 50))
    quality = round(min(quality, float(math_summary["data_quality_score"])), 3)
    regime_inputs = {**math_summary, "data_quality_score": quality}
    regime = classify_regime(regime_inputs)
    regime_gate = assess_regime_gate(signal.action.value, regime, regime_inputs)
    warnings.extend(math_summary.get("warnings", []))
    reasons = [signal.reason]

    direction = signal.action.value if signal.action != Action.HOLD else "NO_TRADE"
    confidence = max(0.0, min(float(signal.confidence), 1.0))

    if signal.action == Action.BUY:
        probability_up, probability_down, probability_neutral = confidence, 0.0, 1 - confidence
    elif signal.action == Action.SELL:
        probability_up, probability_down, probability_neutral = 0.0, confidence, 1 - confidence
    else:
        probability_up, probability_down, probability_neutral = 0.0, 0.0, confidence

    if signal.action == Action.HOLD:
        reasons.append("La strategie a refuse de trader")
    if signal.action != Action.HOLD and not regime_gate["allowed"]:
        direction = "NO_TRADE"
        reasons.extend(regime_gate["reasons"])

    warnings.append("Confiance non calibree: score brut du modele reutilise")
    warnings.extend(regime.get("warnings", []))
    warnings.extend(regime_gate.get("warnings", []))

    bid = _safe_float((price or {}).get("bid"))
    ask = _safe_float((price or {}).get("ask"))
    tradeable = bool((price or {}).get("tradeable", False))
    spread = ask - bid if bid is not None and ask is not None else None

    entry = None
    stop_loss = None
    take_profit = None
    rr = None
    if direction in {"BUY", "SELL"}:
        if not tradeable:
            direction = "NO_TRADE"
            reasons.append("Marche non tradable selon le broker")
        elif bid is not None and ask is not None:
            entry = ask if signal.action == Action.BUY else bid
            stop_loss, take_profit = _bracket(
                signal.action,
                entry,
                settings.stop_loss_pct,
                settings.risk_reward_ratio,
            )
            rr = settings.risk_reward_ratio
        else:
            direction = "NO_TRADE"
            reasons.append("Prix bid/ask indisponible")

    execution_mode = "LIVE" if settings.capital_env == "live" else "DEMO"
    if not settings.trading_enabled:
        execution_mode = "PAPER"
        warnings.append("Ordres bloques par TRADING_ENABLED=false")

    reasons = list(dict.fromkeys(reasons))
    warnings = list(dict.fromkeys(warnings))

    return StructuredSignal(
        symbol=settings.epic,
        timestamp=datetime.now(timezone.utc).isoformat(),
        timeframe=settings.model_granularity,
        direction=direction,
        probability_up=round(probability_up, 4),
        probability_down=round(probability_down, 4),
        probability_neutral=round(probability_neutral, 4),
        raw_model_score=round(confidence, 4),
        calibrated_confidence=round(confidence, 4),
        uncertainty=round(1 - confidence, 4),
        data_quality_score=quality,
        market_regime=regime["regime"],
        expected_move=None,
        expected_value_after_costs=None,
        spread=round(spread, 5) if spread is not None else None,
        slippage_estimate=None,
        recommended_entry=round(entry, 3) if entry is not None else None,
        recommended_sl=round(stop_loss, 3) if stop_loss is not None else None,
        recommended_tp=round(take_profit, 3) if take_profit is not None else None,
        risk_reward_ratio=rr,
        reasons=reasons,
        warnings=warnings,
        model_version=model_version or strategy_name,
        execution_mode=execution_mode,
        math_summary=math_summary,
        regime_details=regime,
        regime_gate=regime_gate,
    ).to_dict()
