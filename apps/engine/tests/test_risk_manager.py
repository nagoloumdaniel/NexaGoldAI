"""Tests du RiskManager durci (limites jour/semaine réelles, série de pertes,
cooldown, kill switch, fail-closed)."""

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.risk.kill_switch import KillSwitch
from app.risk.manager import RiskManager
from app.strategy.base import Action, Signal


def make_settings(**overrides) -> Settings:
    base = dict(
        trading_enabled=True,
        max_risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
        max_weekly_loss_pct=6.0,
        max_open_positions=3,
        max_consecutive_losses=4,
        cooldown_after_loss_minutes=15,
        cooldown_after_consecutive_losses_minutes=60,
    )
    base.update(overrides)
    # _env_file=None : ne pas lire le .env local pendant les tests.
    return Settings(_env_file=None, **base)


def buy_signal(size: float = 1.0) -> Signal:
    return Signal(Action.BUY, 0.8, "test", {}, size)


ACCOUNT = {"balance": 10_000.0, "nav": 10_000.0}

CLEAN_STATS = {
    "realized_pnl_today": 0.0,
    "realized_pnl_week": 0.0,
    "consecutive_losses": 0,
    "last_loss_at": None,
}


def review(settings=None, ks=None, signal=None, account=None, positions=None,
           stats=CLEAN_STATS, price=3300.0, stop=3290.0):
    manager = RiskManager(settings or make_settings(), ks)
    return manager.review(
        signal or buy_signal(),
        account or ACCOUNT,
        positions or [],
        price,
        stop,
        stats,
    )


def test_approves_clean_signal_with_sized_units():
    decision = review()
    assert decision.approved is True
    # 1% de 10 000 = 100 de budget risque ; stop à 10 points -> 10 unités.
    assert decision.units == 10.0


def test_rejects_when_trading_disabled():
    decision = review(settings=make_settings(trading_enabled=False))
    assert decision.approved is False
    assert "TRADING_ENABLED" in decision.reason


def test_rejects_when_kill_switch_locked(tmp_path):
    ks = KillSwitch(tmp_path / "ks.json")
    ks.lock("Cause de test")
    decision = review(ks=ks)
    assert decision.approved is False
    assert "verrouillé" in decision.reason


def test_fail_closed_without_risk_stats():
    decision = review(stats=None)
    assert decision.approved is False
    assert "fail-closed" in decision.reason


def test_daily_loss_counts_realized_losses_even_with_flat_equity(tmp_path):
    """Cas P0 de l'audit : pertes réalisées, equity revenue au niveau du solde.

    L'ancienne implémentation (balance - nav) ne voyait rien. La nouvelle doit
    refuser ET verrouiller le kill switch.
    """
    ks = KillSwitch(tmp_path / "ks.json")
    stats = {**CLEAN_STATS, "realized_pnl_today": -301.0}  # > 3% de 10 000
    decision = review(ks=ks, stats=stats)
    assert decision.approved is False
    assert "Daily loss" in decision.reason
    assert ks.locked is True


def test_daily_loss_combines_realized_and_floating(tmp_path):
    ks = KillSwitch(tmp_path / "ks.json")
    # -200 réalisé + -150 flottant = -350 > limite 300.
    account = {"balance": 10_000.0, "nav": 9_850.0}
    stats = {**CLEAN_STATS, "realized_pnl_today": -200.0}
    decision = review(ks=ks, stats=stats, account=account)
    assert decision.approved is False
    assert ks.locked is True


def test_daily_gain_offsets_floating_loss():
    # +200 réalisé, -250 flottant : perte nette du jour -50, sous la limite.
    account = {"balance": 10_000.0, "nav": 9_750.0}
    stats = {**CLEAN_STATS, "realized_pnl_today": 200.0}
    decision = review(stats=stats, account=account)
    assert decision.approved is True


def test_weekly_loss_limit(tmp_path):
    ks = KillSwitch(tmp_path / "ks.json")
    stats = {**CLEAN_STATS, "realized_pnl_week": -601.0}  # > 6% de 10 000
    decision = review(ks=ks, stats=stats)
    assert decision.approved is False
    assert "Weekly loss" in decision.reason
    assert ks.locked is True


def test_consecutive_losses_lock(tmp_path):
    ks = KillSwitch(tmp_path / "ks.json")
    stats = {**CLEAN_STATS, "consecutive_losses": 4}
    decision = review(ks=ks, stats=stats)
    assert decision.approved is False
    assert "Consecutive losses" in decision.reason
    assert ks.locked is True


def test_cooldown_after_single_recent_loss():
    five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    stats = {**CLEAN_STATS, "consecutive_losses": 1, "last_loss_at": five_min_ago}
    decision = review(stats=stats)
    assert decision.approved is False
    assert "Cooldown" in decision.reason


def test_cooldown_expired_allows_trading():
    old_loss = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    stats = {**CLEAN_STATS, "consecutive_losses": 1, "last_loss_at": old_loss}
    decision = review(stats=stats)
    assert decision.approved is True


def test_longer_cooldown_after_two_consecutive_losses():
    # 20 min après la perte : OK pour 1 perte (15 min), PAS pour 2 (60 min).
    twenty_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    stats = {**CLEAN_STATS, "consecutive_losses": 2, "last_loss_at": twenty_min_ago}
    decision = review(stats=stats)
    assert decision.approved is False
    assert "Cooldown" in decision.reason


def test_max_open_positions():
    positions = [{"ticket": i} for i in range(3)]
    decision = review(positions=positions)
    assert decision.approved is False
    assert "Max open positions" in decision.reason


def test_rejects_invalid_position_multiplier():
    decision = review(signal=buy_signal(size=1.5))
    assert decision.approved is False
    decision = review(signal=buy_signal(size=0.0))
    assert decision.approved is False


def test_sell_signal_gets_negative_units():
    decision = review(signal=Signal(Action.SELL, 0.8, "test", {}, 1.0),
                      price=3300.0, stop=3310.0)
    assert decision.approved is True
    assert decision.units == -10.0
