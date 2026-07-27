"""Zones de liquidité et détection de sweep + réintégration.

Un « sweep » de liquidité (côté achat) : le prix perce brièvement un creux de
référence — là où s'accumulent les stops — puis RÉINTÈGRE rapidement au-dessus
du niveau. C'est le setup de base de LIQUIDITY_SWEEP_TREND_CONTINUATION : la
liquidité prise, le mouvement reprend dans le sens de la tendance supérieure.

Côté vente : miroir sur un sommet de référence.

Fonctions pures sur bougies closes ; les profondeurs/tolérances s'expriment en
fraction d'ATR pour rester invariantes d'échelle.
"""

from dataclasses import dataclass

from app.strategy_v2.market_structure import Swing

BUY = "BUY"
SELL = "SELL"


@dataclass(frozen=True)
class LiquidityLevel:
    price: float
    kind: str  # "LOW" (support/stops sous le marché) | "HIGH"
    swing_indexes: tuple[int, ...]  # swings qui composent le niveau
    strength: int  # nombre de touches (2+ = égalité => pool plus fort)


@dataclass(frozen=True)
class SweepEvent:
    direction: str  # BUY : creux balayé puis réintégré ; SELL : miroir
    level: float
    extreme: float  # plus bas (BUY) / plus haut (SELL) atteint pendant le sweep
    depth: float  # distance niveau -> extrême (positive)
    sweep_index: int  # bougie qui perce le niveau
    reintegration_index: int  # première clôture revenue du bon côté
    speed_bars: int  # bougies entre perce et réintégration (0 = même bougie)
    rejection_strength: float  # 0..1 : position de la clôture de réintégration
    level_strength: int


def find_liquidity_levels(
    swings: list[Swing],
    tolerance: float,
    max_levels: int = 6,
) -> list[LiquidityLevel]:
    """Niveaux de liquidité depuis les swings : chaque swing est un niveau,
    les swings de même type à moins de `tolerance` fusionnent en égalité
    (equal highs/lows), plus forte car elle concentre davantage de stops."""
    levels: list[LiquidityLevel] = []
    for kind in ("LOW", "HIGH"):
        candidates = [s for s in swings if s.kind == kind]
        used: set[int] = set()
        for i, swing in enumerate(candidates):
            if i in used:
                continue
            cluster = [swing]
            for j in range(i + 1, len(candidates)):
                if j in used:
                    continue
                if abs(candidates[j].price - swing.price) <= tolerance:
                    cluster.append(candidates[j])
                    used.add(j)
            # Niveau = extrême du cluster (le plus bas des creux / le plus
            # haut des sommets) : c'est là que sont réellement les stops.
            price = (
                min(s.price for s in cluster)
                if kind == "LOW"
                else max(s.price for s in cluster)
            )
            levels.append(
                LiquidityLevel(
                    price=price,
                    kind=kind,
                    swing_indexes=tuple(s.index for s in cluster),
                    strength=len(cluster),
                )
            )
    # Les plus récents d'abord (dernier swing du cluster), bornés.
    levels.sort(key=lambda level: max(level.swing_indexes), reverse=True)
    return levels[:max_levels]


def detect_sweep(
    candles: list[dict],
    level: LiquidityLevel,
    atr_value: float,
    min_depth_atr: float = 0.1,
    max_depth_atr: float = 1.5,
    max_reintegration_bars: int = 3,
    max_age_bars: int = 30,
) -> SweepEvent | None:
    """Cherche le sweep le plus récent du `level` suivi d'une réintégration.

    Conditions :
    - la perce a lieu APRÈS le dernier swing composant le niveau ;
    - profondeur entre min et max (en ATR) : trop peu = bruit, trop profond =
      vraie cassure, pas un sweep ;
    - clôture de réintégration du bon côté du niveau au plus tard
      `max_reintegration_bars` bougies après la perce (la bougie de perce qui
      clôture déjà du bon côté compte, vitesse 0) ;
    - le tout dans les `max_age_bars` dernières bougies.
    """
    if atr_value <= 0 or not candles:
        return None
    n = len(candles)
    start = max(max(level.swing_indexes) + 1, n - max_age_bars, 0)
    min_depth = min_depth_atr * atr_value
    max_depth = max_depth_atr * atr_value
    is_buy = level.kind == "LOW"

    def pierces(bar: dict) -> bool:
        return bar["low"] < level.price if is_buy else bar["high"] > level.price

    def reintegrated(bar: dict) -> bool:
        return bar["close"] > level.price if is_buy else bar["close"] < level.price

    best: SweepEvent | None = None
    i = start
    while i < n:
        if not pierces(candles[i]):
            i += 1
            continue
        # Une séquence CONTIGUË de bougies sous (au-dessus du) niveau est UN
        # sweep : le budget de réintégration court depuis la première perce et
        # l'extrême couvre toute la séquence (le stop sera placé derrière lui).
        run_start = i
        run_end = i
        while run_end + 1 < n and pierces(candles[run_end + 1]):
            run_end += 1

        reintegration = None
        for j in range(run_start, min(run_start + max_reintegration_bars + 1, n)):
            if reintegrated(candles[j]):
                reintegration = j
                break

        if reintegration is not None:
            window = candles[run_start : max(reintegration, run_end) + 1]
            extreme = (
                min(c["low"] for c in window)
                if is_buy
                else max(c["high"] for c in window)
            )
            depth = (level.price - extreme) if is_buy else (extreme - level.price)
            if min_depth <= depth <= max_depth:
                bar = candles[reintegration]
                bar_range = bar["high"] - bar["low"]
                if bar_range <= 0:
                    rejection = 0.5
                elif is_buy:
                    rejection = (bar["close"] - bar["low"]) / bar_range
                else:
                    rejection = (bar["high"] - bar["close"]) / bar_range
                best = SweepEvent(
                    direction=BUY if is_buy else SELL,
                    level=level.price,
                    extreme=float(extreme),
                    depth=float(depth),
                    sweep_index=run_start,
                    reintegration_index=reintegration,
                    speed_bars=reintegration - run_start,
                    rejection_strength=round(float(rejection), 3),
                    level_strength=level.strength,
                )
        i = max(run_end, reintegration or run_start) + 1
        # On continue : un sweep plus récent remplace le précédent.
    return best


def most_recent_sweep(
    candles: list[dict],
    levels: list[LiquidityLevel],
    atr_value: float,
    direction: str,
    **kwargs,
) -> SweepEvent | None:
    """Meilleur sweep dans la direction donnée parmi les niveaux candidats.

    Priorité : réintégration la plus récente, puis force du niveau (égalités).
    """
    wanted_kind = "LOW" if direction == BUY else "HIGH"
    events = [
        e
        for level in levels
        if level.kind == wanted_kind
        for e in [detect_sweep(candles, level, atr_value, **kwargs)]
        if e is not None
    ]
    if not events:
        return None
    events.sort(key=lambda e: (e.reintegration_index, e.level_strength), reverse=True)
    return events[0]
