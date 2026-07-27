"""Tests bout-en-bout de LiquiditySweepStrategy sur données synthétiques.

Scénario nominal BUY :
- H1/M15 en tendance haussière structurelle (creux et sommets montants) ;
- M5 : creux de référence à 3290, sweep sous ce niveau puis réintégration ;
- M1 : clôture au-dessus du plus haut de la réaction (shift), puis retest de
  ce niveau avec bougie de rejet haussière = dernière bougie close.
"""

from datetime import datetime, timedelta

from app.config import Settings
from app.strategy.base import Action
from app.strategy_v2.state_machine import SetupStateMachine
from app.strategy_v2.sweep_strategy import LiquiditySweepStrategy, SweepConfig

# Mardi 2026-07-28, session Londres/New York.
T0 = datetime(2026, 7, 28, 8, 0)


def make_settings(**overrides) -> Settings:
    base = dict(
        sessions_enabled=True,
        allowed_sessions="LONDON,NEW_YORK",
        avoid_session_edges_minutes=5,
        sweep_require_retest=True,
        sweep_min_risk_reward=2.0,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def build(settings: Settings | None = None, config: SweepConfig | None = None):
    return LiquiditySweepStrategy(
        settings or make_settings(), config or SweepConfig(), SetupStateMachine()
    )


def bar(t: datetime, o, h, low, c) -> dict:
    return {
        "time": t.strftime("%Y-%m-%dT%H:%M:%S"),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": 100,
    }


def path_bars(
    points: list[float], start: datetime, step_minutes: int, spread: float = 0.6
) -> list[dict]:
    return [
        bar(
            start + timedelta(minutes=step_minutes * i),
            p,
            p + spread,
            p - spread,
            p,
        )
        for i, p in enumerate(points)
    ]


def trending_tf(
    start_price: float, start: datetime, step_minutes: int, count: int = 70,
    slope: float = 1.0, wave: float = 3.0,
) -> list[dict]:
    """Zigzag haussier : creux/sommets montants (HH/HL garantis)."""
    points = []
    for i in range(count):
        base = start_price + slope * i
        points.append(base + (wave if i % 4 in (1, 2) else 0.0))
    return path_bars(points, start, step_minutes)


def bearish_tf(start_price, start, step_minutes, count=70, slope=1.0, wave=3.0):
    points = []
    for i in range(count):
        base = start_price - slope * i
        points.append(base - (wave if i % 4 in (1, 2) else 0.0))
    return path_bars(points, start, step_minutes)


def build_m5_with_sweep(start: datetime) -> tuple[list[dict], float, datetime]:
    """M5 : montée, creux de référence à ~3290, re-montée, sweep, réintégration.

    Renvoie (bougies, niveau_du_creux, heure_de_la_réintégration).
    """
    prices = [3270 + 0.8 * i for i in range(50)]  # montée régulière -> ~3309
    candles = path_bars(prices, start, 5, spread=0.5)
    t = start + timedelta(minutes=5 * len(candles))

    def add(o, h, low, c):
        nonlocal t
        candles.append(bar(t, o, h, low, c))
        t += timedelta(minutes=5)

    # Pullback formant le creux de référence à 3290 (swing low fractal).
    for p in (3305, 3298, 3293):
        add(p, p + 0.6, p - 0.6, p - 0.3)
    add(3291, 3291.5, 3289.5, 3290.2)  # creux 3289.5
    for p in (3293, 3297, 3301, 3304):
        add(p, p + 0.8, p - 0.8, p + 0.4)
    # Consolidation au-dessus du niveau.
    for p in (3303, 3302, 3301.5, 3301, 3300.5, 3300):
        add(p, p + 0.7, p - 0.7, p)
    # SWEEP : perce 3289.5 d'environ 1.5 (dans [0.15, 1.5] x ATR) et RÉINTÈGRE
    # dans la même bougie avec une clôture de rejet haute.
    add(3299, 3299.5, 3288.0, 3295.0)
    reintegration_time = t - timedelta(minutes=5)
    # Suite immédiate : stabilisation sous le plus haut de la réaction.
    add(3295.5, 3296.5, 3294.5, 3296.0)
    return candles, 3289.5, reintegration_time


def build_m1_trigger(
    reintegration_time: datetime, shift_level: float, retest: bool = True
) -> list[dict]:
    """M1 : historique neutre, shift au-dessus de `shift_level`, puis retest."""
    hist_start = reintegration_time - timedelta(minutes=70)
    candles = path_bars(
        [3294 + 0.01 * i for i in range(65)], hist_start, 1, spread=0.4
    )
    t = reintegration_time + timedelta(minutes=1)

    def add(o, h, low, c):
        nonlocal t
        candles.append(bar(t, o, h, low, c))
        t += timedelta(minutes=1)

    add(3295.0, 3296.0, 3294.6, 3295.8)
    add(3295.8, shift_level + 1.2, 3295.5, shift_level + 1.0)  # SHIFT
    if retest:
        add(shift_level + 1.0, shift_level + 1.1, shift_level - 0.4, shift_level + 0.2)
        # Bougie de rejet haussière dans la zone de retest = dernier close.
        add(shift_level + 0.1, shift_level + 0.9, shift_level - 0.3, shift_level + 0.8)
    # Bougie en cours de formation (ignorée par la stratégie).
    add(shift_level + 0.8, shift_level + 1.0, shift_level + 0.6, shift_level + 0.9)
    return candles


def nominal_buy_setup():
    h1 = trending_tf(3200, T0 - timedelta(hours=70), 60)
    m15 = trending_tf(3260, T0, 15)
    m5_start = T0 + timedelta(hours=1)
    m5, level, reintegration_time = build_m5_with_sweep(m5_start)
    # Plus haut de la réaction = high de la bougie de sweep (3299.5).
    m1 = build_m1_trigger(reintegration_time, 3299.5)
    return m1, {"M5": m5, "M15": m15, "H1": h1}


def test_nominal_buy_signal():
    strategy = build()
    m1, extra = nominal_buy_setup()
    signal = strategy.evaluate(m1, extra=extra)
    assert signal.action == Action.BUY, signal.reason
    assert signal.features["sweep_level"] == 3289.5
    assert signal.features["sweep_extreme"] == 3288.0
    assert signal.features["stop_loss_pct"] > 0
    assert signal.features["risk_reward_ratio"] == 2.0
    assert strategy.fsm_status()["state"] == "READY_TO_EXECUTE"
    # Le stop est bien SOUS l'extrême du sweep.
    assert signal.features["stop_price_reference"] < 3288.0


def test_blocked_when_h1_bearish():
    strategy = build()
    m1, extra = nominal_buy_setup()
    extra["H1"] = bearish_tf(3400, T0 - timedelta(hours=70), 60)
    signal = strategy.evaluate(m1, extra=extra)
    assert signal.action == Action.HOLD
    assert "non aligné" in signal.reason or "non directionnel" in signal.reason


def test_blocked_outside_allowed_session():
    strategy = build(make_settings(allowed_sessions="ASIA"))
    m1, extra = nominal_buy_setup()  # 09h-10h UTC : hors ASIA
    signal = strategy.evaluate(m1, extra=extra)
    assert signal.action == Action.HOLD
    assert "session" in signal.reason.lower()


def test_waiting_retest_when_no_retest_yet():
    strategy = build()
    h1 = trending_tf(3200, T0 - timedelta(hours=70), 60)
    m15 = trending_tf(3260, T0, 15)
    m5, _level, reintegration_time = build_m5_with_sweep(T0 + timedelta(hours=1))
    m1 = build_m1_trigger(reintegration_time, 3299.5, retest=False)
    signal = strategy.evaluate(m1, extra={"M5": m5, "M15": m15, "H1": h1})
    assert signal.action == Action.HOLD
    assert "retest" in signal.reason.lower()
    assert strategy.fsm_status()["state"] == "WAITING_RETEST"


def test_one_entry_per_setup():
    strategy = build()
    m1, extra = nominal_buy_setup()
    signal = strategy.evaluate(m1, extra=extra)
    assert signal.action == Action.BUY
    # Le Trader confirme l'exécution -> le setup est consommé.
    strategy.mark_signal_consumed(signal.features["trigger_bar_time"])
    replay = strategy.evaluate(m1, extra=extra)
    assert replay.action == Action.HOLD
    assert "déjà exécuté" in replay.reason


def test_insufficient_history_holds():
    strategy = build()
    m1, extra = nominal_buy_setup()
    extra["H1"] = extra["H1"][:10]
    signal = strategy.evaluate(m1, extra=extra)
    assert signal.action == Action.HOLD
    assert "insuffisant" in signal.reason


def test_transitions_are_recorded_with_reasons():
    strategy = build()
    m1, extra = nominal_buy_setup()
    strategy.evaluate(m1, extra=extra)
    transitions = strategy.fsm_status()["recent_transitions"]
    states_reached = [t["to"] for t in transitions]
    for expected in (
        "CONTEXT_VALIDATED",
        "ZONE_DETECTED",
        "SWEEP_DETECTED",
        "REINTEGRATION_CONFIRMED",
        "STRUCTURE_SHIFT_CONFIRMED",
        "WAITING_RETEST",
        "READY_TO_EXECUTE",
    ):
        assert expected in states_reached
    assert all(t["reason"] for t in transitions)
