"""Stratégie LIQUIDITY_SWEEP_TREND_CONTINUATION (v1, paper-only).

Pipeline multi-timeframe, chaque étape matérialisée par la machine à états :

    H1  : contexte — tendance structurelle (HH/HL vs LH/LL) + volatilité
    M15 : la structure doit être alignée avec H1 (pas de CHoCH opposé)
    M5  : zones de liquidité (swings + égalités) → sweep → réintégration rapide
    M1  : shift de microstructure (clôture au-delà de la réaction) puis retest

L'entrée n'est produite que si TOUTES les étapes passent sur la dernière bougie
M1 close. Le stop est structurel (sous/sur l'extrême du sweep + marge ATR), le
TP au RR configuré. La stratégie ne parle jamais au broker : elle émet un
Signal que l'IA (plus tard), puis le RiskManager, peuvent encore refuser.

Aucune bougie en cours de formation n'est utilisée, sur aucun timeframe.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from app.config import Settings
from app.strategy.base import Action, Signal, Strategy
from app.strategy_v2 import state_machine as fsm_states
from app.strategy_v2.liquidity import (
    BUY,
    SELL,
    find_liquidity_levels,
    most_recent_sweep,
)
from app.strategy_v2.market_structure import (
    BEARISH,
    BULLISH,
    analyze_structure,
    atr,
    find_swings,
)
from app.strategy_v2.sessions import in_allowed_session
from app.strategy_v2.state_machine import ForbiddenTransition, SetupStateMachine

logger = logging.getLogger("nexagold.sweep")

_MIN_CANDLES = 60


@dataclass
class SweepConfig:
    swing_lookback: int = 2
    # Fusion des égalités de sommets/creux (fraction de l'ATR M5).
    level_tolerance_atr: float = 0.30
    # Profondeur du sweep : sous min = bruit, au-delà de max = vraie cassure.
    min_depth_atr: float = 0.15
    max_depth_atr: float = 1.50
    max_reintegration_bars: int = 3
    sweep_max_age_bars: int = 24  # bougies M5 (2 h)
    # Retest : distance tolérée entre le creux du retest et le niveau cassé.
    retest_tolerance_atr: float = 0.50
    # Entrée refusée si le prix s'est déjà éloigné du niveau balayé.
    max_extension_atr: float = 1.20
    stop_buffer_atr: float = 0.25
    risk_reward: float = 2.0
    require_retest: bool = True
    # Volatilité H1 extrême (ATR/prix) : pas de nouveau setup.
    max_h1_atr_pct: float = 0.02


def _parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _closed(candles: list[dict] | None) -> list[dict]:
    candles = candles or []
    return candles[:-1] if len(candles) > 1 else candles


class LiquiditySweepStrategy(Strategy):
    """Continuation de tendance après prise de liquidité (XAUUSD, démo only)."""

    name = "liquidity-sweep-v1"
    paper_only = True
    paper_horizon_hours = None
    close_on_profit = False  # sorties structurelles : SL/TP serveur
    extra_granularities = ("M5", "M15", "H1")

    def __init__(self, settings: Settings, config: SweepConfig, fsm: SetupStateMachine):
        self.model_version = "liquidity-sweep-v1"
        self._config = config
        self._fsm = fsm
        self._sessions_enabled = settings.sessions_enabled
        self._allowed_sessions = {
            s.strip().upper()
            for s in settings.allowed_sessions.split(",")
            if s.strip()
        }
        self._avoid_edges = settings.avoid_session_edges_minutes
        self._last_trigger_bar: datetime | None = None
        self._consumed_setups: list[str] = []
        self._pending_setup_id: str | None = None

    # -- Hooks Trader ---------------------------------------------------------

    def mark_signal_consumed(self, bar_time_iso: str | None) -> None:
        """Une seule entrée exécutée par bougie M1 ET par setup."""
        bar_time = _parse_time(bar_time_iso)
        if bar_time is not None:
            self._last_trigger_bar = bar_time
        if self._pending_setup_id is not None:
            self._consumed_setups = (self._consumed_setups + [self._pending_setup_id])[
                -50:
            ]

    def fsm_status(self) -> dict:
        return self._fsm.status()

    # -- Évaluation -----------------------------------------------------------

    def _hold(self, reason: str, features: dict | None = None) -> Signal:
        return Signal(Action.HOLD, 0.0, reason, features or {}, 0.0)

    def _reject(self, reason: str, features: dict | None = None) -> Signal:
        try:
            self._fsm.to(fsm_states.REJECTED, reason)
        except ForbiddenTransition:
            pass  # déjà dans un état terminal
        return self._hold(reason, features)

    def evaluate(
        self,
        candles: list[dict],
        macro_candles: list[dict] | None = None,
        extra: dict[str, list[dict]] | None = None,
    ) -> Signal:
        cfg = self._config
        extra = extra or {}
        self._pending_setup_id: str | None = None
        self._fsm.reset("nouvelle évaluation")

        m1 = _closed(candles)
        m5 = _closed(extra.get("M5"))
        m15 = _closed(extra.get("M15"))
        h1 = _closed(extra.get("H1"))
        for label, series in (("M1", m1), ("M5", m5), ("M15", m15), ("H1", h1)):
            if len(series) < _MIN_CANDLES:
                return self._hold(
                    f"Historique {label} insuffisant ({len(series)} bougies closes)"
                )

        last_m1 = m1[-1]
        now = _parse_time(last_m1.get("time"))
        if now is None:
            return self._hold("Timestamp M1 illisible")

        # 0) Session autorisée ?
        if self._sessions_enabled and not in_allowed_session(
            now, self._allowed_sessions, self._avoid_edges
        ):
            return self._hold(
                f"Hors session autorisée ({','.join(sorted(self._allowed_sessions))})"
            )

        # 1) Contexte H1 + alignement M15.
        h1_structure = analyze_structure(h1, cfg.swing_lookback)
        trend = h1_structure["trend"]
        if trend not in (BULLISH, BEARISH):
            return self._hold(f"Contexte H1 non directionnel ({trend})")
        price = float(last_m1["close"])
        h1_atr_pct = atr(h1) / price if price > 0 else 1.0
        if h1_atr_pct > cfg.max_h1_atr_pct:
            return self._hold(
                f"Volatilité H1 extrême (ATR {h1_atr_pct:.2%} > {cfg.max_h1_atr_pct:.2%})"
            )
        m15_structure = analyze_structure(m15, cfg.swing_lookback)
        if m15_structure["trend"] != trend:
            return self._hold(
                f"M15 ({m15_structure['trend']}) non aligné avec H1 ({trend})"
            )
        opposing_choch = m15_structure["choch"] is not None
        if opposing_choch:
            return self._hold("CHoCH M15 contre la tendance H1 — structure fragilisée")
        direction = BUY if trend == BULLISH else SELL
        self._fsm.to(fsm_states.CONTEXT_VALIDATED, f"H1 {trend}, M15 aligné")

        base_features = {
            "signal_kind": "liquidity_sweep",
            "strategy_version": self.model_version,
            "h1_trend": trend,
            "h1_atr_pct": round(h1_atr_pct, 5),
            "m15_trend": m15_structure["trend"],
        }

        # 2) Zones de liquidité M5.
        atr5 = atr(m5)
        if atr5 <= 0:
            return self._reject("ATR M5 nul — données suspectes", base_features)
        swings5 = find_swings(m5, cfg.swing_lookback)
        levels = [
            level
            for level in find_liquidity_levels(
                swings5, tolerance=cfg.level_tolerance_atr * atr5
            )
            if level.kind == ("LOW" if direction == BUY else "HIGH")
        ]
        if not levels:
            return self._hold("Aucune zone de liquidité M5 exploitable", base_features)
        self._fsm.to(fsm_states.ZONE_DETECTED, f"{len(levels)} zone(s) {direction}")

        # 3) Sweep + réintégration sur M5.
        sweep = most_recent_sweep(
            m5,
            levels,
            atr5,
            direction,
            min_depth_atr=cfg.min_depth_atr,
            max_depth_atr=cfg.max_depth_atr,
            max_reintegration_bars=cfg.max_reintegration_bars,
            max_age_bars=cfg.sweep_max_age_bars,
        )
        if sweep is None:
            return self._hold("Aucun sweep récent réintégré", base_features)
        self._fsm.to(
            fsm_states.SWEEP_DETECTED,
            f"Niveau {sweep.level:.2f} percé de {sweep.depth:.2f} "
            f"(force {sweep.level_strength})",
        )
        self._fsm.to(
            fsm_states.REINTEGRATION_CONFIRMED,
            f"Réintégré en {sweep.speed_bars} bougie(s) M5, "
            f"rejet {sweep.rejection_strength:.0%}",
        )

        setup_id = (
            f"{direction}:{sweep.level:.3f}:"
            f"{m5[sweep.reintegration_index].get('time')}"
        )
        sweep_features = {
            **base_features,
            "direction": direction,
            "sweep_level": round(sweep.level, 3),
            "sweep_extreme": round(sweep.extreme, 3),
            "sweep_depth": round(sweep.depth, 3),
            "sweep_depth_atr": round(sweep.depth / atr5, 3),
            "sweep_speed_bars": sweep.speed_bars,
            "sweep_rejection": sweep.rejection_strength,
            "level_strength": sweep.level_strength,
            "setup_id": setup_id,
        }
        if setup_id in self._consumed_setups:
            return self._reject("Setup déjà exécuté (une entrée par sweep)", sweep_features)

        # 4) Shift de microstructure M1 : clôture au-delà de la réaction.
        reintegration_time = _parse_time(m5[sweep.reintegration_index].get("time"))
        reaction_bars = m5[sweep.sweep_index : sweep.reintegration_index + 1]
        if direction == BUY:
            shift_level = max(c["high"] for c in reaction_bars)
        else:
            shift_level = min(c["low"] for c in reaction_bars)
        m1_after = [
            (i, c)
            for i, c in enumerate(m1)
            if (t := _parse_time(c.get("time"))) is not None
            and reintegration_time is not None
            and t > reintegration_time
        ]
        shift_index = None
        for i, c in m1_after:
            broke = (
                c["close"] > shift_level if direction == BUY else c["close"] < shift_level
            )
            if broke:
                shift_index = i
                break
        if shift_index is None:
            return self._hold(
                f"Pas de shift M1 au-delà de {shift_level:.2f}", sweep_features
            )
        self._fsm.to(
            fsm_states.STRUCTURE_SHIFT_CONFIRMED,
            f"Clôture M1 au-delà de {shift_level:.2f}",
        )
        sweep_features["shift_level"] = round(shift_level, 3)

        # 5) Retest de la zone cassée, déclencheur = dernière bougie M1 close.
        if cfg.require_retest:
            self._fsm.to(fsm_states.WAITING_RETEST, "Retest requis")
            tolerance = cfg.retest_tolerance_atr * atr5
            in_zone = (
                last_m1["low"] <= shift_level + tolerance
                if direction == BUY
                else last_m1["high"] >= shift_level - tolerance
            )
            rejecting = (
                last_m1["close"] > last_m1["open"]
                if direction == BUY
                else last_m1["close"] < last_m1["open"]
            )
            still_valid = (
                last_m1["close"] > sweep.extreme
                if direction == BUY
                else last_m1["close"] < sweep.extreme
            )
            if shift_index >= len(m1) - 1:
                return self._hold(
                    "Shift confirmé — en attente du retest", sweep_features
                )
            if not (in_zone and rejecting and still_valid):
                return self._hold(
                    "Retest non confirmé sur la dernière bougie M1", sweep_features
                )

        # 6) Invalidations d'entrée. L'extension se mesure par rapport à la
        # zone de retest (niveau de shift) : entrer loin au-dessus d'elle,
        # c'est courir après le mouvement au lieu d'acheter le retest.
        entry = float(last_m1["close"])
        extension = (
            entry - shift_level if direction == BUY else shift_level - entry
        )
        if extension > cfg.max_extension_atr * atr5:
            return self._reject(
                f"Mouvement déjà étendu ({extension:.2f} au-delà du retest > "
                f"{cfg.max_extension_atr:.2f} x ATR M5)",
                sweep_features,
            )
        if self._last_trigger_bar is not None and now == self._last_trigger_bar:
            return self._hold("Entrée déjà exécutée sur cette bougie M1", sweep_features)

        if direction == BUY:
            stop_price = sweep.extreme - cfg.stop_buffer_atr * atr5
            stop_pct = (entry - stop_price) / entry
        else:
            stop_price = sweep.extreme + cfg.stop_buffer_atr * atr5
            stop_pct = (stop_price - entry) / entry
        if stop_pct <= 0:
            return self._reject("Stop structurel invalide", sweep_features)

        self._fsm.to(fsm_states.READY_TO_EXECUTE, "Toutes les conditions remplies")
        self._pending_setup_id = setup_id

        confidence = 0.5
        confidence += 0.10 if sweep.level_strength >= 2 else 0.0
        confidence += 0.10 if sweep.rejection_strength >= 0.7 else 0.0
        confidence += 0.05 if sweep.speed_bars <= 1 else 0.0
        confidence = min(confidence, 0.85)

        features = {
            **sweep_features,
            "trigger_bar_time": last_m1.get("time"),
            "entry_reference": round(entry, 3),
            "stop_price_reference": round(stop_price, 3),
            "stop_loss_pct": round(stop_pct, 6),
            "risk_reward_ratio": cfg.risk_reward,
            "m5_atr": round(atr5, 4),
            "fsm": self._fsm.status()["state"],
            "paper_only": True,
        }
        action = Action.BUY if direction == BUY else Action.SELL
        return Signal(
            action,
            confidence,
            (
                f"Sweep {direction} : niveau {sweep.level:.2f} "
                f"(force {sweep.level_strength}) balayé de {sweep.depth:.2f}, "
                f"réintégré en {sweep.speed_bars} bougie(s), shift M1 > "
                f"{shift_level:.2f}, retest confirmé — stop {stop_pct:.2%}, "
                f"RR {cfg.risk_reward:.1f}"
            ),
            features,
            1.0,
        )
