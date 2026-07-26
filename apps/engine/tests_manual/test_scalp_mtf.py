"""Tests de la stratégie scalp M5 multi-timeframe et du tuner adaptatif.

Run: .venv\\Scripts\\python.exe -m tests_manual.test_scalp_mtf
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.learning.adaptive import BOUNDS, DEFAULT_PARAMS, AdaptiveTuner
from app.strategy.base import Action
from app.strategy.scalp_mtf import ScalpM5Strategy


def _candles(
    count: int,
    step_minutes: int,
    drift_per_bar: float,
    start_price: float = 3300.0,
    start: datetime | None = None,
    pattern: list[float] | None = None,
) -> list[dict]:
    """Série synthétique orientée.

    Sans `pattern`, dérive monotone (utile pour les timeframes d'analyse).
    Avec `pattern`, la variation de chaque bougie suit le cycle donné — permet
    une tendance réaliste avec pullbacks (RSI ni à 100 ni à 0).
    """
    start = start or datetime(2026, 7, 20, 9, 0)
    out = []
    price = start_price
    for i in range(count):
        open_ = price
        delta = pattern[i % len(pattern)] if pattern else drift_per_bar
        close = price + delta
        high = max(open_, close) + abs(delta) * 0.4 + 0.05
        low = min(open_, close) - abs(delta) * 0.4 - 0.05
        out.append(
            {
                "time": (start + timedelta(minutes=step_minutes * i)).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                ),
                "open": round(open_, 3),
                "high": round(high, 3),
                "low": round(low, 3),
                "close": round(close, 3),
                "volume": 100,
                "complete": True,
            }
        )
        price = close
    return out


def _fresh_strategy(tmp: Path, enabled: bool = True) -> ScalpM5Strategy:
    return ScalpM5Strategy(AdaptiveTuner(tmp / "state.json", enabled=enabled))


# Tendance M5 avec pullbacks (2 hausses, 1 baisse) : RSI dans une zone saine.
# Le pattern se termine sur une bougie haussière quand (count-2) % 3 != 2
# (la dernière bougie, en cours, est ignorée par la stratégie) : 120 -> ok.
_UP_PATTERN = [0.6, 0.6, -0.6]
_DOWN_PATTERN = [-0.6, -0.6, 0.6]


def _bull_market() -> tuple[list[dict], dict[str, list[dict]]]:
    m5 = _candles(120, 5, 0.0, pattern=_UP_PATTERN)
    extra = {
        "M15": _candles(90, 15, 1.8),
        "M30": _candles(90, 30, 3.5),
        "H1": _candles(90, 60, 7.0),
    }
    return m5, extra


def test_buy_signal_on_aligned_uptrend(tmp: Path) -> None:
    strategy = _fresh_strategy(tmp)
    m5, extra = _bull_market()
    signal = strategy.evaluate(m5, extra=extra)
    assert signal.action == Action.BUY, signal.reason
    assert 0.0 < signal.confidence <= 0.95
    f = signal.features
    assert f["signal_kind"] == "scalp_mtf"
    assert f["stop_loss_pct"] > 0
    assert f["risk_reward_ratio"] == DEFAULT_PARAMS["risk_reward_ratio"]
    assert f["profit_close_min_net"] == DEFAULT_PARAMS["profit_close_min_net"]
    assert f["paper_only"] is True
    assert strategy.close_on_profit is True
    assert strategy.paper_horizon_hours is None
    print("OK  BUY sur tendance haussiere alignee:", signal.reason)


def test_sell_signal_on_aligned_downtrend(tmp: Path) -> None:
    strategy = _fresh_strategy(tmp)
    m5 = _candles(120, 5, 0.0, pattern=_DOWN_PATTERN)
    extra = {
        "M15": _candles(90, 15, -1.8),
        "M30": _candles(90, 30, -3.5),
        "H1": _candles(90, 60, -7.0),
    }
    signal = strategy.evaluate(m5, extra=extra)
    assert signal.action == Action.SELL, signal.reason
    print("OK  SELL sur tendance baissiere alignee:", signal.reason)


def test_hold_when_timeframes_disagree(tmp: Path) -> None:
    strategy = _fresh_strategy(tmp)
    m5 = _candles(120, 5, 0.6)
    extra = {
        "M15": _candles(90, 15, 1.8),
        "M30": _candles(90, 30, -3.5),  # contradiction -> pas de trade
        "H1": _candles(90, 60, 7.0),
    }
    signal = strategy.evaluate(m5, extra=extra)
    assert signal.action == Action.HOLD, signal.reason
    print("OK  HOLD sur timeframes contradictoires:", signal.reason)


def test_hold_when_history_missing(tmp: Path) -> None:
    strategy = _fresh_strategy(tmp)
    m5, extra = _bull_market()
    signal = strategy.evaluate(m5, extra={**extra, "H1": extra["H1"][:10]})
    assert signal.action == Action.HOLD
    signal2 = strategy.evaluate(m5[:20], extra=extra)
    assert signal2.action == Action.HOLD
    signal3 = strategy.evaluate(m5, extra=None)
    assert signal3.action == Action.HOLD
    print("OK  HOLD quand l'historique d'analyse manque")


def test_one_executed_entry_per_m5_bar(tmp: Path) -> None:
    strategy = _fresh_strategy(tmp)
    m5, extra = _bull_market()
    first = strategy.evaluate(m5, extra=extra)
    assert first.action == Action.BUY
    # Un preview (evaluate sans exécution) ne consomme PAS le signal.
    again = strategy.evaluate(m5, extra=extra)
    assert again.action == Action.BUY, "un preview ne doit pas consommer la bougie"
    # Après exécution de l'ordre, la même bougie ne redonne plus d'entrée.
    strategy.mark_signal_consumed(first.features["m5_bar_time"])
    third = strategy.evaluate(m5, extra=extra)
    assert third.action == Action.HOLD, "même bougie M5 -> une seule entrée exécutée"
    print("OK  une seule entree executee par bougie M5 (preview sans effet)")


def test_cooldown_after_loss(tmp: Path) -> None:
    strategy = _fresh_strategy(tmp)
    m5, extra = _bull_market()
    # Perte enregistrée "maintenant" vs bougies de 2026-07-20 : pour tester le
    # cooldown il faut une perte datée juste avant la dernière bougie.
    strategy.tuner.last_loss_at = datetime.now(timezone.utc)
    last_bar = datetime.fromisoformat(m5[-2]["time"]).replace(tzinfo=timezone.utc)
    strategy.tuner.last_loss_at = last_bar - timedelta(minutes=5)
    signal = strategy.evaluate(m5, extra=extra)
    assert signal.action == Action.HOLD, signal.reason
    assert "Cooldown" in signal.reason
    print("OK  cooldown apres une perte:", signal.reason)


def test_tuner_tightens_after_losses(tmp: Path) -> None:
    tuner = AdaptiveTuner(tmp / "loss_state.json", enabled=True)
    for i in range(10):
        tuner.record_trade(pnl=-5.0 if i % 3 else 1.0, side="BUY", source="SL")
    assert tuner.params["min_votes"] == 3, tuner.params
    assert tuner.params["position_size"] < DEFAULT_PARAMS["position_size"]
    assert (
        tuner.params["cooldown_bars_after_loss"]
        > DEFAULT_PARAMS["cooldown_bars_after_loss"]
    )
    status = tuner.status()
    assert status["recent_adjustments"], "les ajustements doivent être journalisés"
    print("OK  le tuner devient plus strict apres des pertes:", tuner.params)


def test_tuner_raises_profit_cushion_on_slippage(tmp: Path) -> None:
    tuner = AdaptiveTuner(tmp / "slip_state.json", enabled=True)
    # Prises de profit qui finissent négatives = le coussin ne couvre pas la
    # latence -> le tuner doit l'augmenter.
    for _ in range(8):
        tuner.record_trade(pnl=-0.05, side="BUY", source="PROFIT_TAKE")
    assert (
        tuner.params["profit_close_min_net"] > DEFAULT_PARAMS["profit_close_min_net"]
    ), tuner.params
    print(
        "OK  coussin de prise de profit releve apres slippage:",
        tuner.params["profit_close_min_net"],
    )


def test_tuner_bounds_and_persistence(tmp: Path) -> None:
    path = tmp / "persist_state.json"
    tuner = AdaptiveTuner(path, enabled=True)
    # Marteler des pertes : tous les paramètres doivent rester dans les bornes.
    for _ in range(60):
        tuner.record_trade(pnl=-3.0, side="SELL", source="SL")
    for name, value in tuner.params.items():
        lo, hi = BOUNDS[name]
        assert lo <= value <= hi, f"{name}={value} hors bornes [{lo}, {hi}]"
    # Rechargement : l'état appris survit au redémarrage.
    reloaded = AdaptiveTuner(path, enabled=True)
    assert reloaded.params == tuner.params
    assert reloaded.last_loss_at is not None
    print("OK  bornes respectees et etat persistant:", tuner.params)


def test_strategy_reads_learned_params(tmp: Path) -> None:
    strategy = _fresh_strategy(tmp)
    for _ in range(60):
        strategy.tuner.record_trade(pnl=-3.0, side="BUY", source="SL")
    assert strategy.tuner.params["min_votes"] == 3
    assert strategy.tuner.params["position_size"] == BOUNDS["position_size"][0]
    _, extra = _bull_market()
    # Après les pertes, la zone RSI apprise est stricte (achat < 60) : il faut
    # une tendance douce avec de vrais pullbacks pour redevenir éligible.
    m5 = _candles(120, 5, 0.0, pattern=[0.6, 0.6, -0.9])
    strategy.tuner.last_loss_at = None  # neutralise le cooldown pour ce test
    signal = strategy.evaluate(m5, extra=extra)
    # Marché totalement aligné : le trade passe encore, mais avec la taille
    # réduite et le seuil de profit appris par le tuner.
    assert signal.action == Action.BUY, signal.reason
    assert signal.position_size == strategy.tuner.params["position_size"]
    assert (
        signal.features["profit_close_min_net"]
        == strategy.tuner.params["profit_close_min_net"]
    )
    assert signal.features["adaptive_params"]["min_votes"] == 3
    print("OK  la strategie applique les parametres appris:", signal.position_size)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        test_buy_signal_on_aligned_uptrend(tmp / "a")
        test_sell_signal_on_aligned_downtrend(tmp / "b")
        test_hold_when_timeframes_disagree(tmp / "c")
        test_hold_when_history_missing(tmp / "d")
        test_one_executed_entry_per_m5_bar(tmp / "e")
        test_cooldown_after_loss(tmp / "f")
        test_tuner_tightens_after_losses(tmp / "g")
        test_tuner_raises_profit_cushion_on_slippage(tmp / "h")
        test_tuner_bounds_and_persistence(tmp / "i")
        test_strategy_reads_learned_params(tmp / "j")
    print("\nTous les tests scalp M5 + tuner adaptatif sont PASSES")


if __name__ == "__main__":
    main()
