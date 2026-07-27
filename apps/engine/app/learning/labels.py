"""Labels par barrière pour l'apprentissage supervisé (Phase 9).

Pour chaque signal CANDIDAT (exécuté ou non), on rejoue les bougies M1 après
l'heure du signal et on détermine ce qui aurait été touché en premier :

    TARGET_FIRST  — l'objectif avant le stop
    STOP_FIRST    — le stop avant l'objectif
    TIMEOUT       — ni l'un ni l'autre dans l'horizon
    AMBIGUOUS     — stop ET objectif touchés dans la MÊME bougie M1 : sans
                    données tick, l'ordre réel est inconnaissable — classé
                    pessimiste (compté comme perte) et marqué ambigu
    INVALID_DATA  — pas assez de bougies après le signal

Règles anti-fuite : seules les bougies STRICTEMENT postérieures à l'heure du
signal sont utilisées ; l'entrée est prise à l'open de la première bougie
suivante (parité avec le backtest et l'exécution réelle).
"""

from dataclasses import asdict, dataclass
from datetime import datetime

TARGET_FIRST = "TARGET_FIRST"
STOP_FIRST = "STOP_FIRST"
TIMEOUT = "TIMEOUT"
AMBIGUOUS = "AMBIGUOUS"
INVALID_DATA = "INVALID_DATA"


@dataclass(frozen=True)
class BarrierLabel:
    outcome: str
    result_r: float | None  # +rr, -1, ou R du close en TIMEOUT ; None si invalide
    bars_to_outcome: int | None
    entry_price: float | None
    mfe_r: float | None
    mae_r: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def _parse(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def label_signal(
    m1_after: list[dict],
    direction: str,
    stop_pct: float,
    risk_reward: float,
    horizon_bars: int = 1440,
) -> BarrierLabel:
    """Label d'un signal à partir des bougies M1 qui le SUIVENT.

    `m1_after` : bougies strictement postérieures au signal, chronologiques.
    L'entrée théorique = open de la première bougie ; stop/objectif dérivés de
    `stop_pct` et `risk_reward` comme dans l'exécution réelle.
    """
    if not m1_after or stop_pct <= 0 or risk_reward <= 0:
        return BarrierLabel(INVALID_DATA, None, None, None, None, None)

    entry = float(m1_after[0]["open"])
    if direction == "BUY":
        stop = entry * (1 - stop_pct)
        target = entry * (1 + stop_pct * risk_reward)
    else:
        stop = entry * (1 + stop_pct)
        target = entry * (1 - stop_pct * risk_reward)
    risk = abs(entry - stop)
    if risk <= 0:
        return BarrierLabel(INVALID_DATA, None, None, None, None, None)

    mfe = 0.0
    mae = 0.0
    window = m1_after[:horizon_bars]
    for i, bar in enumerate(window):
        high, low = float(bar["high"]), float(bar["low"])
        if direction == "BUY":
            mfe = max(mfe, (high - entry) / risk)
            mae = min(mae, (low - entry) / risk)
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            mfe = max(mfe, (entry - low) / risk)
            mae = min(mae, (entry - high) / risk)
            stop_hit = high >= stop
            target_hit = low <= target

        if stop_hit and target_hit:
            # Ordre intrabar inconnaissable sans ticks : hypothèse PESSIMISTE
            # documentée — jamais l'inverse.
            return BarrierLabel(
                AMBIGUOUS, -1.0, i + 1, round(entry, 3),
                round(mfe, 4), round(mae, 4),
            )
        if stop_hit:
            return BarrierLabel(
                STOP_FIRST, -1.0, i + 1, round(entry, 3),
                round(mfe, 4), round(mae, 4),
            )
        if target_hit:
            return BarrierLabel(
                TARGET_FIRST, round(risk_reward, 4), i + 1, round(entry, 3),
                round(mfe, 4), round(mae, 4),
            )

    if len(m1_after) < horizon_bars:
        # Horizon incomplet ET aucune barrière touchée : données insuffisantes
        # pour trancher — on ne fabrique pas un TIMEOUT optimiste.
        return BarrierLabel(
            INVALID_DATA, None, None, round(entry, 3),
            round(mfe, 4), round(mae, 4),
        )
    close = float(window[-1]["close"])
    signed = close - entry if direction == "BUY" else entry - close
    return BarrierLabel(
        TIMEOUT, round(signed / risk, 4), horizon_bars, round(entry, 3),
        round(mfe, 4), round(mae, 4),
    )


def label_from_series(
    m1: list[dict],
    signal_time,
    direction: str,
    stop_pct: float,
    risk_reward: float,
    horizon_bars: int = 1440,
) -> BarrierLabel:
    """Variante pratique : filtre les bougies strictement postérieures au signal."""
    cutoff = _parse(signal_time)
    if cutoff is None:
        return BarrierLabel(INVALID_DATA, None, None, None, None, None)
    after = [
        c for c in m1 if (t := _parse(c.get("time"))) is not None and t > cutoff
    ]
    return label_signal(after, direction, stop_pct, risk_reward, horizon_bars)
