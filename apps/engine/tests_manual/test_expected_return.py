"""Deterministic checks for expected-return strategy research."""

import numpy as np
import pandas as pd

from app.research.expected_return import (
    build_completed_daily_momentum_filter,
    build_expected_return_dataset,
    simulate_event_strategy,
    summarize_simulations,
)


index = pd.date_range("2026-01-01", periods=90, freq="h")
close = pd.Series(
    100.0 + np.linspace(0.0, 10.0, len(index)) + np.sin(np.arange(len(index)) / 2.0),
    index=index,
)
candles = pd.DataFrame(
    {
        "open": close - 0.1,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": 100.0 + np.sin(np.arange(len(index))) * 10.0,
    },
    index=index,
)
dataset, model_columns = build_expected_return_dataset(candles, horizon=2)
assert len(dataset) > 0
assert "_future_return" not in model_columns
assert "_close" not in model_columns
first_time = dataset.index[0]
first_position = candles.index.get_loc(first_time)
expected_target = candles["close"].iloc[first_position + 2] / candles["close"].iloc[first_position] - 1.0
assert np.isclose(dataset.loc[first_time, "_future_return"], expected_target)

daily_index = pd.date_range("2025-01-01", periods=110, freq="D")
daily_candles = pd.DataFrame(
    {"close": np.linspace(100.0, 200.0, len(daily_index))}, index=daily_index
)
daily_filter = build_completed_daily_momentum_filter(daily_candles, lookback_days=100)
assert daily_filter.iloc[:101].isna().all()
assert daily_filter.iloc[101:].all()

event_index = pd.date_range("2026-01-05", periods=5, freq="h")
event_data = pd.DataFrame({"_close": [100.0, 101.0, 102.0, 103.0, 104.0]}, index=event_index)
event_data["_regime_name"] = ["BULLISH_TREND"] * len(event_data)
event_data["_regime_trend"] = ["BULLISH"] * len(event_data)
event_data["_regime_volatility"] = ["NORMAL_VOLATILITY"] * len(event_data)
predictions = np.full(len(event_data), 0.01)
free = simulate_event_strategy(
    event_data,
    predictions,
    horizon=2,
    threshold=0.005,
    granularity="H1",
    cost_bps_per_side=0.0,
    financing_bps_per_day=0.0,
)
free_metrics = summarize_simulations([free])
assert len(free.trades) == 2
assert free.trades["entry_position"].tolist() == [0, 2]
assert free.trades["exit_position"].tolist() == [2, 4]
assert np.isclose(free.trades.iloc[0]["mfe_pct"], 0.02)
assert np.isclose(free.trades.iloc[0]["mae_pct"], 0.0)
assert np.isclose(free.trades.iloc[0]["profit_capture_ratio"], 1.0)
assert free.trades.iloc[0]["entry_regime_name"] == "BULLISH_TREND"
assert np.isclose(free_metrics["total_return"], 0.04)
assert free_metrics["by_entry_regime"]["BULLISH_TREND"]["trades"] == 2

costly = simulate_event_strategy(
    event_data,
    predictions,
    horizon=2,
    threshold=0.005,
    granularity="H1",
    cost_bps_per_side=5.0,
    financing_bps_per_day=2.0,
)
costly_metrics = summarize_simulations([costly])
assert costly_metrics["total_return"] < free_metrics["total_return"]
assert costly_metrics["expectancy_per_trade"] < free_metrics["expectancy_per_trade"]

half_sized = simulate_event_strategy(
    event_data,
    predictions,
    horizon=2,
    threshold=0.005,
    granularity="H1",
    cost_bps_per_side=0.0,
    financing_bps_per_day=0.0,
    position_sizes=np.full(len(event_data), 0.5),
)
half_sized_metrics = summarize_simulations([half_sized])
assert 0 < half_sized_metrics["total_return"] < free_metrics["total_return"]
assert np.isclose(half_sized.trades["position_size"], 0.5).all()

flat = simulate_event_strategy(
    event_data,
    predictions,
    horizon=2,
    threshold=None,
    granularity="H1",
    cost_bps_per_side=5.0,
    financing_bps_per_day=2.0,
)
flat_metrics = summarize_simulations([flat])
assert flat_metrics["trades"] == 0
assert flat_metrics["total_return"] == 0.0

short_predictions = np.full(len(event_data), -0.01)
long_only = simulate_event_strategy(
    event_data,
    short_predictions,
    horizon=2,
    threshold=0.005,
    granularity="H1",
    cost_bps_per_side=0.0,
    financing_bps_per_day=0.0,
    direction_mode="LONG_ONLY",
)
assert summarize_simulations([long_only])["trades"] == 0

bracket_index = pd.date_range("2026-01-05", periods=3, freq="h")
bracket_data = pd.DataFrame(
    {
        "_close": [100.0, 100.5, 101.0],
        "_high": [100.0, 102.0, 101.0],
        "_low": [100.0, 98.0, 101.0],
    },
    index=bracket_index,
)
bracket = simulate_event_strategy(
    bracket_data,
    np.full(len(bracket_data), 0.01),
    horizon=2,
    threshold=0.005,
    granularity="H1",
    cost_bps_per_side=0.0,
    financing_bps_per_day=0.0,
    stop_loss_pct=0.01,
    risk_reward_ratio=1.5,
)
assert len(bracket.trades) == 1
assert bracket.trades.iloc[0]["exit_reason"] == "STOP_LOSS"
assert bracket.trades.iloc[0]["exit_position"] == 1
assert np.isclose(bracket.trades.iloc[0]["gross_return"], -0.01)
assert np.isclose(bracket.trades.iloc[0]["mfe_r"], 2.0)
assert np.isclose(bracket.trades.iloc[0]["mae_r"], 2.0)
assert np.isclose(bracket.trades.iloc[0]["realised_r"], -1.0)
assert np.isclose(bracket.trades.iloc[0]["profit_capture_ratio"], 0.0)
bracket_metrics = summarize_simulations([bracket])
assert np.isclose(bracket_metrics["stop_loss_rate"], 1.0)
assert np.isclose(bracket_metrics["average_mae_r"], 2.0)

trailing_data = pd.DataFrame(
    {
        "_close": [100.0, 102.0, 103.0, 101.0],
        "_high": [100.0, 102.5, 103.5, 101.5],
        "_low": [100.0, 101.5, 102.5, 100.5],
    },
    index=pd.date_range("2026-01-06", periods=4, freq="h"),
)
trailing = simulate_event_strategy(
    trailing_data,
    np.full(len(trailing_data), 0.01),
    horizon=3,
    threshold=0.005,
    granularity="H1",
    cost_bps_per_side=0.0,
    financing_bps_per_day=0.0,
    stop_loss_pct=0.01,
    risk_reward_ratio=0.0,
    exit_policy="TRAILING_STOP",
    trailing_activation_r=1.0,
)
assert len(trailing.trades) == 1
assert trailing.trades.iloc[0]["exit_reason"] == "TRAILING_STOP"
assert np.isclose(trailing.trades.iloc[0]["realised_r"], 1.97)
trailing_metrics = summarize_simulations([trailing])
assert np.isclose(trailing_metrics["trailing_stop_rate"], 1.0)

print("OK: expected-return research valide")
