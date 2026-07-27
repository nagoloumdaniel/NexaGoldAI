"""Structure de marché : swings, HH/HL/LH/LL, BOS, CHoCH, tendance.

Fonctions pures sur des listes chronologiques de bougies closes
`{time, open, high, low, close, volume}`. Aucune bougie future n'est utilisée :
un swing à l'index i n'est confirmé qu'après `lookback` bougies closes à sa
droite, et il est daté/indexé à sa bougie d'origine.

Vocabulaire :
- swing HIGH/LOW : extremum local fractal (plus haut/bas que `lookback` voisins
  de chaque côté) ;
- HH/HL/LH/LL : position d'un swing par rapport au précédent de même type ;
- BOS (break of structure) : clôture au-delà du dernier swing dans le sens de
  la tendance (continuation) ;
- CHoCH (change of character) : clôture au-delà du dernier swing CONTRE la
  tendance en cours (premier signe de retournement).
"""

from dataclasses import dataclass

BULLISH = "BULLISH"
BEARISH = "BEARISH"
RANGE = "RANGE"
UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class Swing:
    index: int
    time: str | None
    price: float
    kind: str  # "HIGH" | "LOW"
    label: str | None = None  # HH/HL/LH/LL une fois classifié

    def with_label(self, label: str) -> "Swing":
        return Swing(self.index, self.time, self.price, self.kind, label)


def find_swings(candles: list[dict], lookback: int = 2) -> list[Swing]:
    """Extrema locaux fractals, en alternance HIGH/LOW stricte.

    En cas de deux swings consécutifs du même type, seul le plus extrême est
    conservé (l'autre était un faux relais).
    """
    raw: list[Swing] = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        high = candles[i]["high"]
        low = candles[i]["low"]
        left = candles[i - lookback : i]
        right = candles[i + 1 : i + 1 + lookback]
        # Strict à gauche, tolérant (>=/<=) à droite : un plateau (égalité de
        # sommets/creux, fréquent sur l'or) est daté à sa PREMIÈRE bougie au
        # lieu de disparaître du fractal.
        if all(high > c["high"] for c in left) and all(
            high >= c["high"] for c in right
        ):
            raw.append(Swing(i, candles[i].get("time"), float(high), "HIGH"))
        if all(low < c["low"] for c in left) and all(low <= c["low"] for c in right):
            raw.append(Swing(i, candles[i].get("time"), float(low), "LOW"))

    raw.sort(key=lambda s: (s.index, s.kind))
    alternated: list[Swing] = []
    for swing in raw:
        if not alternated or alternated[-1].kind != swing.kind:
            alternated.append(swing)
            continue
        last = alternated[-1]
        keep_new = (
            swing.price > last.price if swing.kind == "HIGH" else swing.price < last.price
        )
        if keep_new:
            alternated[-1] = swing
    return alternated


def label_swings(swings: list[Swing]) -> list[Swing]:
    """HH/HL/LH/LL par comparaison au précédent swing de même type."""
    labelled: list[Swing] = []
    last_by_kind: dict[str, Swing] = {}
    for swing in swings:
        previous = last_by_kind.get(swing.kind)
        if previous is None:
            labelled.append(swing)
        elif swing.kind == "HIGH":
            labelled.append(swing.with_label("HH" if swing.price > previous.price else "LH"))
        else:
            labelled.append(swing.with_label("HL" if swing.price > previous.price else "LL"))
        last_by_kind[swing.kind] = swing
    return labelled


def analyze_structure(candles: list[dict], lookback: int = 2) -> dict:
    """Tendance structurelle + derniers événements BOS/CHoCH.

    Tendance :
    - BULLISH : dernier high HH et dernier low HL ;
    - BEARISH : dernier high LH et dernier low LL ;
    - RANGE   : labels contradictoires (HH+LL ou LH+HL) ;
    - UNCERTAIN : moins de deux swings de chaque type.
    """
    swings = label_swings(find_swings(candles, lookback))
    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]

    out: dict = {
        "swings": swings,
        "last_high": highs[-1] if highs else None,
        "last_low": lows[-1] if lows else None,
        "trend": UNCERTAIN,
        "bos": None,
        "choch": None,
    }
    if not highs or not lows:
        return out

    last_high_label = highs[-1].label
    last_low_label = lows[-1].label
    if last_high_label is None or last_low_label is None:
        return out

    if last_high_label == "HH" and last_low_label == "HL":
        trend = BULLISH
    elif last_high_label == "LH" and last_low_label == "LL":
        trend = BEARISH
    else:
        trend = RANGE
    out["trend"] = trend

    # BOS / CHoCH sur la dernière clôture, par rapport aux derniers swings.
    close = float(candles[-1]["close"])
    if trend == BULLISH:
        if close > highs[-1].price:
            out["bos"] = {"direction": "UP", "level": highs[-1].price}
        if close < lows[-1].price:
            out["choch"] = {"direction": "DOWN", "level": lows[-1].price}
    elif trend == BEARISH:
        if close < lows[-1].price:
            out["bos"] = {"direction": "DOWN", "level": lows[-1].price}
        if close > highs[-1].price:
            out["choch"] = {"direction": "UP", "level": highs[-1].price}
    return out


def atr(candles: list[dict], period: int = 14) -> float:
    """ATR de Wilder (mêmes conventions que la stratégie scalp)."""
    trs = []
    for prev, cur in zip(candles[:-1], candles[1:], strict=False):
        trs.append(
            max(
                cur["high"] - cur["low"],
                abs(cur["high"] - prev["close"]),
                abs(cur["low"] - prev["close"]),
            )
        )
    if not trs:
        return 0.0
    if len(trs) < period:
        return sum(trs) / len(trs)
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value
