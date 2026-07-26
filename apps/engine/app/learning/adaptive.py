"""Tuner adaptatif de la stratégie scalp.

Apprentissage autonome et borné : après chaque trade clôturé, le tuner met à
jour ses statistiques ; tous les N trades il ré-évalue les paramètres de la
stratégie (sévérité du filtre de tendance, stop ATR, seuil de prise de profit,
cooldown après perte, taille de position) à l'intérieur de bornes dures.

Chaque ajustement est journalisé (raison + avant/après + horodatage) et l'état
complet est persisté en JSON — le bot reprend son apprentissage après un
redémarrage et le dashboard peut afficher ce que l'IA a changé et pourquoi.

Ce n'est volontairement PAS un optimiseur libre : les bornes empêchent
l'auto-apprentissage de dériver vers des réglages destructeurs.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("nexagold.adaptive")

# Paramètres pilotés par l'apprentissage, avec leurs bornes dures [min, max].
DEFAULT_PARAMS: dict[str, float] = {
    # Nombre de timeframes d'analyse (M15/M30/H1) devant être alignés.
    "min_votes": 2,
    # Stop = max(plancher, ATR14 M5 * multiplicateur).
    "atr_multiplier": 2.0,
    "stop_floor_pct": 0.0015,
    # TP de secours (le vrai objectif est la prise de profit anticipée).
    "risk_reward_ratio": 2.0,
    # Zones RSI M5 interdites (pas d'achat suracheté / de vente survendue).
    "rsi_max_entry": 75.0,
    "rsi_min_entry": 25.0,
    # Barres M5 d'attente après une perte avant de reprendre un signal.
    "cooldown_bars_after_loss": 3,
    # Gain net minimal (devise du compte) avant de clôturer une position
    # gagnante — couvre la latence de clôture et le slippage.
    "profit_close_min_net": 0.5,
    # Multiplicateur 0..1 appliqué à la taille calculée par le RiskManager.
    "position_size": 1.0,
}

BOUNDS: dict[str, tuple[float, float]] = {
    "min_votes": (2, 3),
    "atr_multiplier": (1.0, 4.0),
    "stop_floor_pct": (0.001, 0.005),
    "risk_reward_ratio": (1.5, 4.0),
    "rsi_max_entry": (60.0, 85.0),
    "rsi_min_entry": (15.0, 40.0),
    "cooldown_bars_after_loss": (0, 12),
    "profit_close_min_net": (0.2, 10.0),
    "position_size": (0.25, 1.0),
}

_INT_PARAMS = {"min_votes", "cooldown_bars_after_loss"}

# Fenêtre d'analyse (derniers trades) et cadence d'adaptation.
_WINDOW = 30
_ADAPT_EVERY = 8
_MAX_TRADES_KEPT = 300
_MAX_ADJUSTMENTS_KEPT = 200


def _clamp(name: str, value: float) -> float:
    lo, hi = BOUNDS[name]
    value = min(max(value, lo), hi)
    if name in _INT_PARAMS:
        value = int(round(value))
    return value


class AdaptiveTuner:
    """État d'apprentissage persistant + règles d'auto-ajustement bornées."""

    def __init__(self, state_path: Path, enabled: bool = True):
        self._path = Path(state_path)
        self._enabled = enabled
        self.params: dict[str, float] = dict(DEFAULT_PARAMS)
        self._trades: list[dict] = []
        self._adjustments: list[dict] = []
        self._trades_since_adapt = 0
        self.last_loss_at: datetime | None = None
        self._load()

    # -- Persistance ----------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            state = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("État adaptatif illisible (%s) — repart des défauts", exc)
            return
        params = state.get("params") or {}
        for key in DEFAULT_PARAMS:
            if key in params:
                self.params[key] = _clamp(key, float(params[key]))
        self._trades = list(state.get("trades") or [])[-_MAX_TRADES_KEPT:]
        self._adjustments = list(state.get("adjustments") or [])[-_MAX_ADJUSTMENTS_KEPT:]
        self._trades_since_adapt = int(state.get("trades_since_adapt") or 0)
        raw = state.get("last_loss_at")
        if raw:
            try:
                self.last_loss_at = datetime.fromisoformat(raw)
            except ValueError:
                self.last_loss_at = None

    def _save(self) -> None:
        payload = {
            "params": self.params,
            "trades": self._trades[-_MAX_TRADES_KEPT:],
            "adjustments": self._adjustments[-_MAX_ADJUSTMENTS_KEPT:],
            "trades_since_adapt": self._trades_since_adapt,
            "last_loss_at": self.last_loss_at.isoformat() if self.last_loss_at else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self._path)
        except OSError as exc:
            logger.warning("Impossible de persister l'état adaptatif: %s", exc)

    # -- Enregistrement des trades -------------------------------------------

    def record_trade(self, pnl: float, side: str, source: str) -> None:
        """Appelé par le Trader à chaque clôture (profit, SL, TP, horizon)."""
        now = datetime.now(timezone.utc)
        self._trades.append(
            {
                "pnl": round(float(pnl), 4),
                "side": side,
                "source": source,
                "at": now.isoformat(),
            }
        )
        self._trades = self._trades[-_MAX_TRADES_KEPT:]
        if pnl < 0:
            self.last_loss_at = now
        self._trades_since_adapt += 1
        if self._enabled and self._trades_since_adapt >= _ADAPT_EVERY:
            self._adapt()
            self._trades_since_adapt = 0
        self._save()

    # -- Règles d'adaptation --------------------------------------------------

    def _set(self, name: str, value: float, reason: str, changes: list[dict]) -> None:
        new = _clamp(name, value)
        old = self.params[name]
        if new == old:
            return
        self.params[name] = new
        changes.append({"param": name, "from": old, "to": new, "reason": reason})

    def _adapt(self) -> None:
        window = self._trades[-_WINDOW:]
        if len(window) < _ADAPT_EVERY:
            return
        pnls = [t["pnl"] for t in window]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        win_rate = len(wins) / len(pnls)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        profit_takes = [t for t in window if t.get("source") == "PROFIT_TAKE"]
        slipped = [t for t in profit_takes if t["pnl"] <= 0]

        changes: list[dict] = []
        p = self.params

        # Trop de pertes -> filtre plus strict, moins d'exposition, pause plus
        # longue après une perte.
        if win_rate < 0.45:
            self._set("min_votes", 3, f"Win rate {win_rate:.0%} < 45%", changes)
            self._set(
                "cooldown_bars_after_loss",
                p["cooldown_bars_after_loss"] + 2,
                f"Win rate {win_rate:.0%} < 45%",
                changes,
            )
            self._set(
                "position_size",
                p["position_size"] - 0.25,
                f"Win rate {win_rate:.0%} < 45%",
                changes,
            )
            self._set(
                "rsi_max_entry", p["rsi_max_entry"] - 3, "Resserrage zone RSI", changes
            )
            self._set(
                "rsi_min_entry", p["rsi_min_entry"] + 3, "Resserrage zone RSI", changes
            )
        # Bonne période -> on relâche prudemment pour reprendre du débit.
        elif win_rate > 0.65:
            self._set("min_votes", 2, f"Win rate {win_rate:.0%} > 65%", changes)
            self._set(
                "cooldown_bars_after_loss",
                p["cooldown_bars_after_loss"] - 1,
                f"Win rate {win_rate:.0%} > 65%",
                changes,
            )
            self._set(
                "position_size",
                p["position_size"] + 0.25,
                f"Win rate {win_rate:.0%} > 65%",
                changes,
            )

        # Pertes trop lourdes face aux gains -> stop plus serré.
        if wins and losses and avg_loss > 3.0 * max(avg_win, 1e-9):
            self._set(
                "atr_multiplier",
                p["atr_multiplier"] - 0.25,
                f"Perte moyenne {avg_loss:.2f} > 3x gain moyen {avg_win:.2f}",
                changes,
            )

        # Des prises de profit finissent <= 0 : la latence/le slippage mangent
        # le gain -> exiger un coussin net plus grand avant de clôturer.
        if slipped:
            self._set(
                "profit_close_min_net",
                p["profit_close_min_net"] + 0.25,
                f"{len(slipped)} prise(s) de profit clôturée(s) <= 0 (slippage)",
                changes,
            )
        # Toutes les prises de profit passent largement -> on peut clôturer
        # un peu plus tôt (revenir doucement vers le seuil de base).
        elif (
            len(profit_takes) >= 5
            and min(t["pnl"] for t in profit_takes) > 2 * p["profit_close_min_net"]
            and p["profit_close_min_net"] > DEFAULT_PARAMS["profit_close_min_net"]
        ):
            self._set(
                "profit_close_min_net",
                p["profit_close_min_net"] - 0.25,
                "Prises de profit toutes confortables — clôture plus rapide",
                changes,
            )

        # Série de pertes en cours -> pause plus longue.
        tail = pnls[-4:]
        if len(tail) == 4 and all(x < 0 for x in tail):
            self._set(
                "cooldown_bars_after_loss",
                p["cooldown_bars_after_loss"] + 2,
                "4 pertes consécutives",
                changes,
            )

        if changes:
            entry = {
                "at": datetime.now(timezone.utc).isoformat(),
                "window_trades": len(window),
                "win_rate": round(win_rate, 3),
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
                "changes": changes,
            }
            self._adjustments.append(entry)
            self._adjustments = self._adjustments[-_MAX_ADJUSTMENTS_KEPT:]
            logger.info("Auto-ajustement de la stratégie: %s", changes)

    # -- Introspection (API / dashboard) --------------------------------------

    def status(self) -> dict:
        window = self._trades[-_WINDOW:]
        pnls = [t["pnl"] for t in window]
        wins = sum(1 for x in pnls if x > 0)
        return {
            "enabled": self._enabled,
            "params": dict(self.params),
            "bounds": {k: list(v) for k, v in BOUNDS.items()},
            "recorded_trades": len(self._trades),
            "window": {
                "trades": len(window),
                "wins": wins,
                "losses": sum(1 for x in pnls if x < 0),
                "win_rate": round(wins / len(pnls), 3) if pnls else None,
                "total_pnl": round(sum(pnls), 2),
            },
            "last_loss_at": self.last_loss_at.isoformat() if self.last_loss_at else None,
            "trades_since_adapt": self._trades_since_adapt,
            "adapt_every": _ADAPT_EVERY,
            "recent_adjustments": self._adjustments[-10:],
            "state_path": str(self._path),
        }
