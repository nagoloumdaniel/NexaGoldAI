"""Sessions de trading (UTC) pour le déclenchement des setups.

Fenêtres approximatives, volontairement simples (pas de DST par place de
cotation — tout est raisonné en UTC comme le reste du moteur) :
- ASIA      00:00 – 07:00
- LONDON    07:00 – 16:00
- NEW_YORK  12:30 – 21:00

`avoid_edges_minutes` retire les premières/dernières minutes de chaque fenêtre
(les ouvertures/clôtures de session sont erratiques sur l'or).
"""

from datetime import datetime, time

SESSION_WINDOWS: dict[str, tuple[time, time]] = {
    "ASIA": (time(0, 0), time(7, 0)),
    "LONDON": (time(7, 0), time(16, 0)),
    "NEW_YORK": (time(12, 30), time(21, 0)),
}


def _shift(t: time, minutes: int) -> time:
    total = t.hour * 60 + t.minute + minutes
    total = max(0, min(total, 23 * 60 + 59))
    return time(total // 60, total % 60)


def active_sessions(now: datetime, avoid_edges_minutes: int = 0) -> list[str]:
    """Sessions actives à l'instant donné (UTC), bords exclus."""
    current = now.time()
    out = []
    for name, (start, end) in SESSION_WINDOWS.items():
        begin = _shift(start, avoid_edges_minutes)
        finish = _shift(end, -avoid_edges_minutes)
        if begin <= current < finish:
            out.append(name)
    return out


def in_allowed_session(
    now: datetime, allowed: set[str], avoid_edges_minutes: int = 0
) -> bool:
    return bool(set(active_sessions(now, avoid_edges_minutes)) & allowed)
