"""Validation de la qualité d'une série de bougies (Phase 3 de la refonte).

Fonctions pures (testables sans broker ni DB) qui détectent :
- bougies malformées (high < low, OHLC incohérents, prix non positifs) ;
- doublons et timestamps non croissants ;
- trous de cotation (bougies manquantes), en excluant la fermeture du week-end ;
- données périmées (dernière bougie trop vieille alors que le marché est ouvert) ;
- données figées (série de bougies OHLC identiques : flux mort ou marché gelé).

Le score 0..1 sert de gate : les consommateurs (stratégie, modèles) doivent
refuser de décider sous un seuil — on ne « répare » jamais silencieusement.
"""

from datetime import datetime, timedelta, timezone

_GRAN_MINUTES = {
    "M1": 1,
    "M3": 3,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D": 1440,
}

# Nombre de bougies consécutives strictement identiques (OHLC) à partir duquel
# on considère le flux figé. Sur l'or, même en basse liquidité, des dizaines de
# bougies au tick près identiques sont anormales.
_FROZEN_RUN = 10

# Au-delà de ce multiple du pas de la granularité sans nouvelle bougie (marché
# ouvert), la série est périmée.
_STALE_STEPS = 3


def _parse_time(value) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _market_closed_gap(start: datetime, end: datetime) -> bool:
    """True si l'intervalle recouvre la fermeture hebdomadaire de l'or.

    XAUUSD cote environ du dimanche 22h UTC au vendredi 21h UTC. Tout trou qui
    contient un moment du samedi (UTC) est traité comme fermeture de marché,
    pas comme un trou de données.
    """
    cursor = start
    while cursor <= end:
        if cursor.weekday() == 5:  # samedi
            return True
        cursor += timedelta(hours=12)
    return end.weekday() == 5


def _is_market_likely_closed(now: datetime) -> bool:
    """Fenêtre de fermeture hebdomadaire approximative (UTC, marge d'1 h)."""
    wd = now.weekday()
    if wd == 5:  # samedi
        return True
    if wd == 4 and now.hour >= 20:  # vendredi soir
        return True
    if wd == 6 and now.hour < 23:  # dimanche avant la réouverture
        return True
    return False


def validate_candles(
    candles: list[dict],
    granularity: str,
    now: datetime | None = None,
    max_issues_listed: int = 20,
) -> dict:
    """Rapport de qualité d'une série chronologique de bougies."""
    now = now or datetime.now(timezone.utc)
    step_minutes = _GRAN_MINUTES.get(granularity)
    issues: list[dict] = []

    def add_issue(kind: str, detail: str) -> None:
        if len(issues) < max_issues_listed:
            issues.append({"kind": kind, "detail": detail})

    if step_minutes is None:
        return {
            "granularity": granularity,
            "candles": len(candles or []),
            "score": 0.0,
            "valid": False,
            "issues": [{"kind": "UNKNOWN_GRANULARITY", "detail": granularity}],
        }
    if not candles:
        return {
            "granularity": granularity,
            "candles": 0,
            "score": 0.0,
            "valid": False,
            "issues": [{"kind": "EMPTY_SERIES", "detail": "Aucune bougie"}],
        }

    step = timedelta(minutes=step_minutes)
    malformed = 0
    unparseable = 0
    duplicates = 0
    out_of_order = 0
    missing_bars = 0
    gap_events = 0

    previous_time: datetime | None = None
    frozen_run = 1
    longest_frozen_run = 1
    previous_ohlc: tuple | None = None

    for candle in candles:
        when = _parse_time(candle.get("time"))
        if when is None:
            unparseable += 1
            add_issue("UNPARSEABLE_TIME", str(candle.get("time")))
            continue

        try:
            o = float(candle["open"])
            h = float(candle["high"])
            low = float(candle["low"])
            c = float(candle["close"])
        except (KeyError, TypeError, ValueError):
            malformed += 1
            add_issue("MISSING_FIELDS", when.isoformat())
            continue

        if (
            min(o, h, low, c) <= 0
            or h < low
            or h < max(o, c) - 1e-9
            or low > min(o, c) + 1e-9
        ):
            malformed += 1
            add_issue(
                "MALFORMED_OHLC",
                f"{when.isoformat()} O={o} H={h} L={low} C={c}",
            )

        if previous_time is not None:
            if when == previous_time:
                duplicates += 1
                add_issue("DUPLICATE_TIME", when.isoformat())
            elif when < previous_time:
                out_of_order += 1
                add_issue(
                    "OUT_OF_ORDER",
                    f"{when.isoformat()} après {previous_time.isoformat()}",
                )
            else:
                gap = when - previous_time
                if gap > step and not _market_closed_gap(previous_time, when):
                    missed = int(gap / step) - 1
                    if missed > 0:
                        missing_bars += missed
                        gap_events += 1
                        add_issue(
                            "GAP",
                            f"{missed} bougie(s) manquante(s) entre "
                            f"{previous_time.isoformat()} et {when.isoformat()}",
                        )

        ohlc = (o, h, low, c)
        if previous_ohlc is not None and ohlc == previous_ohlc:
            frozen_run += 1
            longest_frozen_run = max(longest_frozen_run, frozen_run)
        else:
            frozen_run = 1
        previous_ohlc = ohlc
        previous_time = when if previous_time is None or when > previous_time else previous_time

    frozen = longest_frozen_run >= _FROZEN_RUN
    if frozen:
        add_issue("FROZEN_DATA", f"{longest_frozen_run} bougies OHLC identiques")

    last_time = _parse_time(candles[-1].get("time"))
    age_seconds = (now - last_time).total_seconds() if last_time else None
    stale = False
    if age_seconds is not None and not _is_market_likely_closed(now):
        stale = age_seconds > _STALE_STEPS * step.total_seconds()
        if stale:
            add_issue(
                "STALE_DATA",
                f"Dernière bougie vieille de {int(age_seconds // 60)} min "
                f"(> {_STALE_STEPS} x {step_minutes} min, marché ouvert)",
            )

    total = len(candles)
    # Pénalités proportionnelles, plafonnées pour rester dans [0, 1].
    penalty = (
        (malformed + unparseable) / total * 2.0
        + duplicates / total
        + out_of_order / total * 2.0
        + min(missing_bars / total, 0.5)
        + (0.3 if frozen else 0.0)
        + (0.3 if stale else 0.0)
    )
    score = round(max(0.0, min(1.0, 1.0 - penalty)), 3)

    return {
        "granularity": granularity,
        "candles": total,
        "first_time": _parse_time(candles[0].get("time")).isoformat()
        if _parse_time(candles[0].get("time"))
        else None,
        "last_time": last_time.isoformat() if last_time else None,
        "age_seconds": int(age_seconds) if age_seconds is not None else None,
        "malformed": malformed,
        "unparseable": unparseable,
        "duplicates": duplicates,
        "out_of_order": out_of_order,
        "missing_bars": missing_bars,
        "gap_events": gap_events,
        "longest_frozen_run": longest_frozen_run,
        "frozen": frozen,
        "stale": stale,
        "score": score,
        # Seuil aligné sur le gate de régime existant (0.80 dans regime.py).
        "valid": score >= 0.8,
        "issues": issues,
    }
