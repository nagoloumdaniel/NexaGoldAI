"""Compact mathematical diagnostics for XAU/USD candles.

The goal is not to create hundreds of indicators, but to expose a small,
causal, testable summary used by the structured signal and later regime engine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import log, sqrt
from statistics import mean, pstdev


def _floats(candles: list[dict], key: str) -> list[float]:
    out: list[float] = []
    for candle in candles:
        try:
            out.append(float(candle[key]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _pct_change(values: list[float]) -> list[float]:
    return [
        values[i] / values[i - 1] - 1
        for i in range(1, len(values))
        if values[i - 1] != 0
    ]


def _slope(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    n = len(values)
    xs = list(range(n))
    x_mean = mean(xs)
    y_mean = mean(values)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)) / denom


def _atr(candles: list[dict], period: int) -> float | None:
    if len(candles) < period + 1:
        return None
    ranges: list[float] = []
    recent = candles[-period:]
    previous_close = float(candles[-period - 1]["close"])
    for candle in recent:
        high = float(candle["high"])
        low = float(candle["low"])
        true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        ranges.append(true_range)
        previous_close = float(candle["close"])
    return mean(ranges)


@dataclass
class MathSummary:
    simple_return_1: float | None
    log_return_1: float | None
    cumulative_return: float | None
    momentum_3: float | None
    momentum_12: float | None
    momentum_acceleration: float | None
    realised_volatility_20: float | None
    volatility_ratio_5_20: float | None
    atr_14: float | None
    atr_pct_14: float | None
    zscore_20: float | None
    regression_slope_20: float | None
    trend_strength: float | None
    data_quality_score: float
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def build_math_summary(candles: list[dict], min_count: int = 50) -> dict:
    closes = _floats(candles, "close")
    warnings: list[str] = []
    if len(closes) < 2:
        return MathSummary(
            simple_return_1=None,
            log_return_1=None,
            cumulative_return=None,
            momentum_3=None,
            momentum_12=None,
            momentum_acceleration=None,
            realised_volatility_20=None,
            volatility_ratio_5_20=None,
            atr_14=None,
            atr_pct_14=None,
            zscore_20=None,
            regression_slope_20=None,
            trend_strength=None,
            data_quality_score=0.0,
            warnings=["Historique insuffisant"],
        ).to_dict()

    returns = _pct_change(closes)
    last = closes[-1]
    first = closes[0]
    simple_return_1 = returns[-1] if returns else None
    log_return_1 = log(last / closes[-2]) if closes[-2] > 0 and last > 0 else None
    cumulative_return = last / first - 1 if first != 0 else None

    def momentum(window: int) -> float | None:
        if len(closes) <= window or closes[-window - 1] == 0:
            return None
        return last / closes[-window - 1] - 1

    mom3 = momentum(3)
    mom12 = momentum(12)
    accel = mom3 - mom12 if mom3 is not None and mom12 is not None else None

    vol20 = pstdev(returns[-20:]) * sqrt(20) if len(returns) >= 20 else None
    vol5 = pstdev(returns[-5:]) if len(returns) >= 5 else None
    vol20_raw = pstdev(returns[-20:]) if len(returns) >= 20 else None
    vol_ratio = (
        vol5 / vol20_raw
        if vol5 is not None and vol20_raw is not None and vol20_raw > 0
        else None
    )

    atr14 = None
    try:
        atr14 = _atr(candles, 14)
    except (KeyError, TypeError, ValueError):
        warnings.append("ATR indisponible: OHLC incomplet")
    atr_pct = atr14 / last if atr14 is not None and last else None

    zscore = None
    if len(closes) >= 20:
        window = closes[-20:]
        sigma = pstdev(window)
        zscore = (last - mean(window)) / sigma if sigma > 0 else 0.0

    slope20 = _slope(closes[-20:]) if len(closes) >= 20 else None
    trend_strength = slope20 / last if slope20 is not None and last else None

    quality = min(len(closes) / max(min_count, 1), 1.0)
    if quality < 1.0:
        warnings.append("Nombre de bougies inferieur au minimum attendu")
    if any(value <= 0 for value in closes):
        warnings.append("Prix non positif detecte")
        quality = min(quality, 0.5)

    return MathSummary(
        simple_return_1=_round(simple_return_1),
        log_return_1=_round(log_return_1),
        cumulative_return=_round(cumulative_return),
        momentum_3=_round(mom3),
        momentum_12=_round(mom12),
        momentum_acceleration=_round(accel),
        realised_volatility_20=_round(vol20),
        volatility_ratio_5_20=_round(vol_ratio),
        atr_14=_round(atr14),
        atr_pct_14=_round(atr_pct),
        zscore_20=_round(zscore),
        regression_slope_20=_round(slope20),
        trend_strength=_round(trend_strength),
        data_quality_score=round(quality, 3),
        warnings=warnings,
    ).to_dict()


def _round(value: float | None) -> float | None:
    return round(value, 8) if value is not None else None
