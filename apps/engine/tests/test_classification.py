"""Tests du classificateur post-trade."""

from app.analysis.classification import (
    BAD_BAD,
    BAD_GOOD,
    GOOD_BAD,
    GOOD_GOOD,
    INCONCLUSIVE,
    classify_trade,
)


def test_clean_win():
    v = classify_trade(result_r=2.0, mfe_r=2.1, mae_r=-0.3, risk_reward=2.0,
                       exit_source="TP")
    assert v.classification == GOOD_GOOD
    assert v.error_category == "NONE"


def test_lucky_win_near_stop_is_bad_decision():
    v = classify_trade(result_r=1.2, mfe_r=1.5, mae_r=-0.95, risk_reward=2.0,
                       exit_source="PROFIT_TAKE")
    assert v.classification == BAD_GOOD
    assert v.error_category == "NEAR_STOP_RECOVERY"


def test_normal_statistical_loss_is_good_decision():
    v = classify_trade(result_r=-1.0, mfe_r=0.4, mae_r=-1.0, risk_reward=2.0,
                       exit_source="SL")
    assert v.classification == GOOD_BAD
    assert v.error_category == "NORMAL_STATISTICAL_LOSS"


def test_target_too_ambitious():
    # A presque atteint 3R avant de revenir au stop.
    v = classify_trade(result_r=-1.0, mfe_r=2.4, mae_r=-1.0, risk_reward=3.0,
                       exit_source="SL")
    assert v.classification == GOOD_BAD
    assert v.error_category == "TARGET_TOO_AMBITIOUS"


def test_stop_too_tight_when_over_1r_then_stopped():
    v = classify_trade(result_r=-1.0, mfe_r=1.3, mae_r=-1.0, risk_reward=4.0,
                       exit_source="SL")
    assert v.classification == GOOD_BAD
    assert v.error_category == "STOP_TOO_TIGHT"


def test_late_entry_never_breathed():
    v = classify_trade(result_r=-1.0, mfe_r=0.05, mae_r=-1.0, risk_reward=2.0,
                       exit_source="SL")
    assert v.classification == BAD_BAD
    assert v.error_category == "LATE_ENTRY"


def test_timeout_and_missing_data_are_inconclusive():
    assert classify_trade(-0.2, 0.5, -0.6, 2.0, "TIMEOUT").classification == INCONCLUSIVE
    assert classify_trade(None, None, None, None, "SL").classification == INCONCLUSIVE
