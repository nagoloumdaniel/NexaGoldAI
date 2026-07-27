"""Stratégie scalp M5 multi-timeframe (BUY et SELL, prise de profit anticipée).

Principe demandé par l'opérateur :
- l'ANALYSE se fait sur H1, M30 et M15 (votes de tendance par timeframe) ;
- l'ENTRÉE se fait sur M5 uniquement, dans le sens des timeframes alignés ;
- la SORTIE n'attend pas le take-profit : le moteur (Trader) ferme la position
  dès que son P&L net dépasse un petit seuil couvrant latence + slippage
  (`close_on_profit=True`) ; le SL serveur reste la protection en cas d'erreur.

Les paramètres sensibles (sévérité de l'alignement, stop ATR, zones RSI,
cooldown après perte, seuil de prise de profit, taille) sont pilotés par
l'AdaptiveTuner qui apprend des trades clôturés — voir learning/adaptive.py.

Stratégie paper-only : compte démo obligatoire, jamais promue en réel
automatiquement (cf. verdict backtest 2023-2026 : pas d'edge démontré).
"""

import logging
from datetime import datetime, timedelta

from app.learning.adaptive import AdaptiveTuner
from app.strategy.base import Action, Signal, Strategy

logger = logging.getLogger("nexagold.scalp")

_ANALYSIS_GRANULARITIES = ("M15", "M30", "H1")
# Bougies closes minimales par timeframe pour des indicateurs stables.
_MIN_CANDLES = 60
_M5 = timedelta(minutes=5)


# -- Indicateurs (pur python : pas de dépendance pandas dans la boucle live) --


def _ema(values: list[float], period: int) -> float:
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes: list[float], period: int) -> float:
    gains, losses = [], []
    for prev, cur in zip(closes[:-1], closes[1:], strict=False):
        delta = cur - prev
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    if len(gains) < period:
        return 50.0
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, loss in zip(gains[period:], losses[period:], strict=False):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _atr(candles: list[dict], period: int = 14) -> float:
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
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _macd_hist(closes: list[float]) -> float:
    if len(closes) < 35:
        return 0.0
    macd_series = []
    # Série MACD sur la fin de l'historique pour pouvoir lisser la signal line.
    for i in range(len(closes) - 9, len(closes)):
        window = closes[: i + 1]
        macd_series.append(_ema(window, 12) - _ema(window, 26))
    signal = _ema(macd_series, 9)
    return macd_series[-1] - signal


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _trend_vote(candles: list[dict]) -> tuple[int, dict]:
    """Vote de tendance d'un timeframe d'analyse : +1 haussier, -1 baissier, 0 neutre.

    Trois composantes (EMA20/EMA50, RSI14, histogramme MACD) ; le timeframe ne
    vote que si au moins deux composantes sont d'accord.
    """
    closes = [c["close"] for c in candles]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    rsi14 = _rsi(closes, 14)
    hist = _macd_hist(closes)

    score = 0
    score += 1 if ema20 > ema50 else -1
    score += 1 if rsi14 > 52 else (-1 if rsi14 < 48 else 0)
    score += 1 if hist > 0 else -1
    vote = 1 if score >= 2 else (-1 if score <= -2 else 0)
    detail = {
        "ema20": round(ema20, 3),
        "ema50": round(ema50, 3),
        "rsi14": round(rsi14, 2),
        "macd_hist": round(hist, 4),
        "vote": vote,
    }
    return vote, detail


class ScalpM5Strategy(Strategy):
    """Entrée M5 dans le sens de l'alignement H1/M30/M15, sortie au premier profit."""

    name = "scalp-m5-mtf"
    paper_only = True
    # Pas de sortie temporelle : la position sort au premier profit net ou au SL.
    paper_horizon_hours = None
    close_on_profit = True
    extra_granularities = _ANALYSIS_GRANULARITIES

    def __init__(self, tuner: AdaptiveTuner):
        self.tuner = tuner
        self.model_version = "scalp-m5-mtf-v1"
        # Une seule ENTRÉE EXÉCUTÉE par bougie M5 (la boucle tourne plus vite
        # que la granularité d'entrée). Marqué par le Trader via
        # mark_signal_consumed() après exécution — pas dans evaluate(), sinon
        # un simple preview du dashboard consommerait le signal de la bougie.
        self._last_signal_bar: datetime | None = None

    def mark_signal_consumed(self, bar_time_iso: str | None) -> None:
        """Appelé par le Trader quand un ordre issu de ce signal est exécuté."""
        bar_time = _parse_time(bar_time_iso)
        if bar_time is not None:
            self._last_signal_bar = bar_time

    @property
    def profit_close_min_net(self) -> float:
        return float(self.tuner.params["profit_close_min_net"])

    @property
    def stop_loss_floor_pct(self) -> float:
        return float(self.tuner.params["stop_floor_pct"])

    @property
    def stop_loss_atr_multiplier(self) -> float:
        return float(self.tuner.params["atr_multiplier"])

    @property
    def risk_reward_ratio(self) -> float:
        return float(self.tuner.params["risk_reward_ratio"])

    def _hold(self, reason: str, features: dict | None = None) -> Signal:
        return Signal(Action.HOLD, 0.0, reason, features or {}, 0.0)

    def evaluate(
        self,
        candles: list[dict],
        macro_candles: list[dict] | None = None,
        extra: dict[str, list[dict]] | None = None,
    ) -> Signal:
        p = self.tuner.params
        extra = extra or {}

        # La dernière bougie M5 est en cours de formation : on ne raisonne que
        # sur des bougies closes pour ne pas décider sur un prix qui repeint.
        m5 = candles[:-1] if len(candles) > 1 else candles
        if len(m5) < _MIN_CANDLES:
            return self._hold(f"Historique M5 insuffisant ({len(m5)} bougies closes)")

        analysis: dict[str, list[dict]] = {}
        for gran in _ANALYSIS_GRANULARITIES:
            tf_candles = extra.get(gran) or []
            tf_closed = tf_candles[:-1] if len(tf_candles) > 1 else tf_candles
            if len(tf_closed) < _MIN_CANDLES:
                return self._hold(
                    f"Historique {gran} insuffisant ({len(tf_closed)} bougies closes)"
                )
            analysis[gran] = tf_closed

        # 1) Votes de tendance des timeframes d'analyse.
        votes: dict[str, dict] = {}
        bulls = bears = 0
        for gran, tf_candles in analysis.items():
            vote, detail = _trend_vote(tf_candles)
            votes[gran] = detail
            bulls += vote == 1
            bears += vote == -1

        min_votes = int(p["min_votes"])
        if bulls >= min_votes and bears == 0:
            direction = Action.BUY
        elif bears >= min_votes and bulls == 0:
            direction = Action.SELL
        else:
            return self._hold(
                f"Timeframes non alignés (haussiers={bulls}, baissiers={bears}, "
                f"requis={min_votes} sans contradiction)",
                {"signal_kind": "scalp_mtf", "votes": votes},
            )

        closes = [c["close"] for c in m5]
        last = m5[-1]
        last_bar_time = _parse_time(last.get("time"))

        base_features = {
            "signal_kind": "scalp_mtf",
            "votes": votes,
            "direction_votes": bulls if direction == Action.BUY else bears,
        }

        # 2) Cooldown après perte : l'IA impose une pause (apprise) avant de
        # reprendre un signal.
        cooldown_bars = int(p["cooldown_bars_after_loss"])
        if cooldown_bars > 0 and self.tuner.last_loss_at and last_bar_time:
            elapsed = last_bar_time - self.tuner.last_loss_at.replace(tzinfo=None)
            if elapsed < cooldown_bars * _M5:
                remaining = cooldown_bars - int(elapsed / _M5)
                return self._hold(
                    f"Cooldown après perte : encore {max(remaining, 0)} bougie(s) M5",
                    base_features,
                )

        # 3) Une seule entrée exécutée par bougie M5.
        if last_bar_time and self._last_signal_bar == last_bar_time:
            return self._hold(
                "Entrée déjà exécutée sur cette bougie M5", base_features
            )

        # 4) Déclencheur d'entrée sur M5 : micro-tendance et bougie de
        # confirmation dans le sens des timeframes d'analyse, RSI hors zone
        # d'épuisement (pas d'achat suracheté, pas de vente survendue).
        ema9 = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        rsi7 = _rsi(closes, 7)
        rsi14 = _rsi(closes, 14)
        candle_up = last["close"] > last["open"]

        trigger_features = {
            **base_features,
            "m5_ema9": round(ema9, 3),
            "m5_ema21": round(ema21, 3),
            "m5_rsi7": round(rsi7, 2),
            "m5_rsi14": round(rsi14, 2),
        }

        if direction == Action.BUY:
            triggered = ema9 > ema21 and candle_up and rsi7 >= 50
            exhausted = rsi14 >= float(p["rsi_max_entry"])
        else:
            triggered = ema9 < ema21 and not candle_up and rsi7 <= 50
            exhausted = rsi14 <= float(p["rsi_min_entry"])

        if exhausted:
            return self._hold(
                f"{direction.value} refusé : RSI14 M5 {rsi14:.1f} en zone d'épuisement",
                trigger_features,
            )
        if not triggered:
            return self._hold(
                f"Tendance {direction.value} alignée mais pas de déclencheur M5",
                trigger_features,
            )

        # 5) Stop ATR (plancher appris) ; TP de secours via risk/reward — la
        # sortie normale reste la prise de profit anticipée du moteur.
        atr = _atr(m5, 14)
        price = last["close"]
        atr_pct = atr / price if price > 0 else 0.0
        stop_pct = max(float(p["stop_floor_pct"]), atr_pct * float(p["atr_multiplier"]))

        aligned = bulls if direction == Action.BUY else bears
        confidence = min(0.5 + 0.15 * aligned + (0.05 if abs(rsi7 - 50) > 10 else 0.0), 0.95)

        features = {
            **trigger_features,
            "m5_bar_time": last_bar_time.isoformat() if last_bar_time else None,
            "m5_atr14": round(atr, 4),
            "m5_atr_pct": round(atr_pct, 6),
            "stop_loss_pct": round(stop_pct, 6),
            "risk_reward_ratio": float(p["risk_reward_ratio"]),
            "profit_close_min_net": float(p["profit_close_min_net"]),
            "adaptive_params": {k: v for k, v in p.items()},
            "paper_only": True,
        }
        tf_txt = ", ".join(
            f"{g}={'+' if votes[g]['vote'] == 1 else '-' if votes[g]['vote'] == -1 else '0'}"
            for g in _ANALYSIS_GRANULARITIES
        )
        return Signal(
            direction,
            confidence,
            (
                f"Scalp {direction.value} : {aligned}/3 timeframes alignés ({tf_txt}), "
                f"déclencheur M5 (EMA9/21, RSI7 {rsi7:.0f}), stop {stop_pct:.2%}, "
                f"sortie au premier profit net >= {p['profit_close_min_net']:.2f}"
            ),
            features,
            float(p["position_size"]),
        )
