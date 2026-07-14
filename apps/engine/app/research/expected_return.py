"""Nested walk-forward research for a direct expected-return strategy.

The production classifier predicts a coarse direction class. This module
tests a different hypothesis: regress the forward return itself, then trade
only predictions whose expected move clears a threshold selected on earlier
validation data.

Nothing in this module changes the live strategy or model registry.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.model_selection import TimeSeriesSplit

from app.research.features import build_features

DEFAULT_REGRESSOR_PARAMS = {
    "n_estimators": 400,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_child_samples": 40,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}

EXPECTED_MOVE_THRESHOLDS = (0.001, 0.002, 0.003, 0.004, 0.005, 0.0075, 0.01)

_BARS_PER_DAY = {
    "M1": 24 * 60,
    "M5": 24 * 12,
    "M15": 24 * 4,
    "M30": 24 * 2,
    "H1": 24,
    "H4": 6,
    "D1": 1,
}


@dataclass
class EventSimulation:
    """Internal marked-to-market result for one contiguous test segment."""

    index: pd.Index
    equity_curve: np.ndarray
    bar_returns: np.ndarray
    trades: pd.DataFrame
    active_bars: float


def build_expected_return_dataset(
    candles: pd.DataFrame,
    horizon: int = 24,
    macro_df: pd.DataFrame | None = None,
    rate_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Build causal features and the close-to-close forward-return target."""
    if horizon < 1:
        raise ValueError("horizon must be at least one bar")

    features = build_features(candles, macro_df, rate_df)
    model_columns = list(features.columns)
    data = features.copy()
    close = candles["close"].astype(float)
    data["_close"] = close
    data["_high"] = candles["high"].astype(float)
    data["_low"] = candles["low"].astype(float)
    data["_future_return"] = close.shift(-horizon) / close - 1.0
    data = data.replace([np.inf, -np.inf], np.nan).dropna()
    return data, model_columns


def build_completed_daily_momentum_filter(
    candles: pd.DataFrame, lookback_days: int = 100
) -> pd.Series:
    """Allow long entries only after positive completed-day momentum.

    The daily signal is shifted by one observed trading day. Intraday bars on
    day D therefore only use a daily close available before day D began.
    """
    if lookback_days < 2:
        raise ValueError("lookback_days must be at least two")
    if not isinstance(candles.index, pd.DatetimeIndex):
        raise ValueError("candles must use a DatetimeIndex")

    day = pd.Series(candles.index.normalize(), index=candles.index)
    daily_close = candles["close"].astype(float).groupby(day).last()
    completed_momentum = daily_close.pct_change(lookback_days).shift(1)
    daily_allowed = (completed_momentum > 0).where(completed_momentum.notna())
    return day.map(daily_allowed).rename("daily_momentum_allowed")


def make_regressor(params: dict | None = None) -> LGBMRegressor:
    return LGBMRegressor(**(params or DEFAULT_REGRESSOR_PARAMS))


def _elapsed_days(index: pd.Index, start: int, end: int, bars_per_day: int) -> float:
    nominal = (end - start) / bars_per_day
    try:
        elapsed = (index[end] - index[start]).total_seconds() / 86400.0
    except (AttributeError, TypeError):
        elapsed = nominal
    # Calendar time is conservative around weekends and market closures.
    return max(float(elapsed), float(nominal), 0.0)


def simulate_event_strategy(
    data: pd.DataFrame,
    predictions: np.ndarray,
    horizon: int,
    threshold: float | None,
    granularity: str,
    cost_bps_per_side: float,
    financing_bps_per_day: float,
    direction_mode: str = "BOTH",
    position_filter: np.ndarray | None = None,
    position_sizes: np.ndarray | None = None,
    stop_loss_pct: float = 0.0,
    risk_reward_ratio: float = 0.0,
    stop_loss_atr_multiplier: float = 0.0,
    stop_loss_atr_column: str = "atr_14",
) -> EventSimulation:
    """Trade non-overlapping fixed-horizon events and mark them to market.

    A prediction is observed at a bar close. The position is entered at that
    close, held for exactly ``horizon`` bars and exited at the future close.
    Both long and short positions are charged the same financing rate, which
    intentionally avoids relying on a broker's variable short-side credit.
    """
    if len(data) != len(predictions):
        raise ValueError("data and predictions must have the same length")
    if horizon < 1:
        raise ValueError("horizon must be at least one bar")
    if cost_bps_per_side < 0 or financing_bps_per_day < 0:
        raise ValueError("costs cannot be negative")
    if stop_loss_pct < 0 or stop_loss_atr_multiplier < 0:
        raise ValueError("stop loss settings cannot be negative")
    bracket_enabled = stop_loss_pct > 0 or stop_loss_atr_multiplier > 0
    if bracket_enabled and risk_reward_ratio <= 0:
        raise ValueError("risk_reward_ratio must be positive when a stop is used")
    direction_mode = direction_mode.upper()
    if direction_mode not in {"BOTH", "LONG_ONLY", "SHORT_ONLY"}:
        raise ValueError("direction_mode must be BOTH, LONG_ONLY or SHORT_ONLY")

    count = len(data)
    equity = np.ones(count, dtype=float)
    close = data["_close"].to_numpy(dtype=float)
    if bracket_enabled:
        missing_ohlc = {"_high", "_low"} - set(data.columns)
        if missing_ohlc:
            raise ValueError(f"bracket simulation requires: {sorted(missing_ohlc)}")
        if stop_loss_atr_multiplier > 0 and stop_loss_atr_column not in data.columns:
            raise ValueError(f"ATR stop column not found: {stop_loss_atr_column}")
        high = data["_high"].to_numpy(dtype=float)
        low = data["_low"].to_numpy(dtype=float)
    else:
        high = low = close
    predictions = np.asarray(predictions, dtype=float)
    if position_filter is None:
        allowed_positions = np.ones(count, dtype=bool)
    else:
        if len(position_filter) != count:
            raise ValueError("position_filter must have the same length as data")
        allowed_positions = np.asarray(position_filter, dtype=bool)
    if position_sizes is None:
        sizes = np.ones(count, dtype=float)
    else:
        if len(position_sizes) != count:
            raise ValueError("position_sizes must have the same length as data")
        sizes = np.asarray(position_sizes, dtype=float)
        if not np.isfinite(sizes).all() or (sizes < 0).any() or (sizes > 1).any():
            raise ValueError("position_sizes must be finite values between zero and one")
    cost_per_side = cost_bps_per_side / 1e4
    financing_per_day = financing_bps_per_day / 1e4
    bars_per_day = _BARS_PER_DAY.get(granularity, 24)
    trades: list[dict] = []
    active_bars = 0
    capital = 1.0
    cursor = 0

    while cursor < count:
        equity[cursor] = capital
        exit_position = cursor + horizon
        if exit_position >= count:
            equity[cursor:] = capital
            break

        prediction = predictions[cursor]
        predicted_direction = 1 if prediction > 0 else -1
        direction_allowed = (
            direction_mode == "BOTH"
            or (direction_mode == "LONG_ONLY" and predicted_direction > 0)
            or (direction_mode == "SHORT_ONLY" and predicted_direction < 0)
        )
        should_trade = (
            threshold is not None
            and np.isfinite(prediction)
            and abs(prediction) >= threshold
            and direction_allowed
            and allowed_positions[cursor]
            and sizes[cursor] > 0
        )
        if not should_trade:
            cursor += 1
            continue

        direction = predicted_direction
        position_size = sizes[cursor]
        entry_price = close[cursor]
        entry_capital = capital
        equity[cursor] = entry_capital * (1.0 - cost_per_side * position_size)

        entry_stop_pct = stop_loss_pct
        if stop_loss_atr_multiplier > 0:
            atr_stop_pct = (
                float(data.iloc[cursor][stop_loss_atr_column])
                * stop_loss_atr_multiplier
            )
            entry_stop_pct = max(entry_stop_pct, atr_stop_pct)

        if direction > 0:
            stop_price = entry_price * (1.0 - entry_stop_pct)
            take_profit_price = entry_price * (
                1.0 + entry_stop_pct * risk_reward_ratio
            )
        else:
            stop_price = entry_price * (1.0 + entry_stop_pct)
            take_profit_price = entry_price * (
                1.0 - entry_stop_pct * risk_reward_ratio
            )

        actual_exit_position = exit_position
        actual_exit_price = close[exit_position]
        exit_reason = "HORIZON"

        for marked_position in range(cursor + 1, exit_position + 1):
            stop_hit = bracket_enabled and (
                (direction > 0 and low[marked_position] <= stop_price)
                or (direction < 0 and high[marked_position] >= stop_price)
            )
            take_profit_hit = bracket_enabled and (
                (direction > 0 and high[marked_position] >= take_profit_price)
                or (direction < 0 and low[marked_position] <= take_profit_price)
            )
            if stop_hit:
                # Pessimistic ordering when both levels are touched in one bar.
                marked_price = stop_price
                actual_exit_position = marked_position
                actual_exit_price = stop_price
                exit_reason = "STOP_LOSS"
            elif take_profit_hit:
                marked_price = take_profit_price
                actual_exit_position = marked_position
                actual_exit_price = take_profit_price
                exit_reason = "TAKE_PROFIT"
            else:
                marked_price = close[marked_position]

            elapsed_days = _elapsed_days(
                data.index, cursor, marked_position, bars_per_day
            )
            gross_mark = (
                position_size
                * direction
                * (marked_price / entry_price - 1.0)
            )
            financing = position_size * elapsed_days * financing_per_day
            execution_cost = position_size * cost_per_side
            if stop_hit or take_profit_hit or marked_position == exit_position:
                execution_cost += position_size * cost_per_side
            marked_return = gross_mark - financing - execution_cost
            equity[marked_position] = entry_capital * (1.0 + marked_return)
            if stop_hit or take_profit_hit:
                break

        holding_days = _elapsed_days(
            data.index, cursor, actual_exit_position, bars_per_day
        )
        gross_return = (
            position_size * direction * (actual_exit_price / entry_price - 1.0)
        )
        financing_return = position_size * holding_days * financing_per_day
        execution_return = position_size * 2.0 * cost_per_side
        net_return = gross_return - execution_return - financing_return
        capital = entry_capital * (1.0 + net_return)
        equity[actual_exit_position] = capital
        active_bars += (actual_exit_position - cursor) * position_size
        trades.append(
            {
                "entry_time": data.index[cursor],
                "exit_time": data.index[actual_exit_position],
                "entry_position": cursor,
                "exit_position": actual_exit_position,
                "direction": "BUY" if direction > 0 else "SELL",
                "prediction": float(prediction),
                "position_size": float(position_size),
                "stop_loss_pct": float(entry_stop_pct),
                "gross_return": float(gross_return),
                "execution_return": float(execution_return),
                "financing_return": float(financing_return),
                "net_return": float(net_return),
                "holding_days": float(holding_days),
                "exit_reason": exit_reason,
            }
        )
        # Re-entry at the same close is allowed after the previous exit.
        cursor = actual_exit_position

    if count:
        bar_returns = np.empty(count, dtype=float)
        bar_returns[0] = equity[0] - 1.0
        bar_returns[1:] = equity[1:] / equity[:-1] - 1.0
    else:
        bar_returns = np.array([], dtype=float)

    return EventSimulation(
        index=data.index,
        equity_curve=equity,
        bar_returns=bar_returns,
        trades=pd.DataFrame(trades),
        active_bars=active_bars,
    )


def _profit_factor(returns: np.ndarray) -> float | None:
    wins = returns[returns > 0].sum()
    losses = returns[returns < 0].sum()
    return float(wins / abs(losses)) if losses < 0 else None


def _direction_summary(trades: pd.DataFrame, direction: str) -> dict:
    if trades.empty:
        returns = np.array([], dtype=float)
    else:
        returns = trades.loc[trades["direction"] == direction, "net_return"].to_numpy(
            dtype=float
        )
    return {
        "trades": int(len(returns)),
        "compounded_return": float(np.prod(1.0 + returns) - 1.0)
        if len(returns)
        else 0.0,
        "profit_factor": _profit_factor(returns),
        "win_rate": float((returns > 0).mean()) if len(returns) else 0.0,
        "expectancy_per_trade": float(returns.mean()) if len(returns) else 0.0,
    }


def _observed_bars_per_year(simulations: list[EventSimulation]) -> float:
    observations = 0
    elapsed_years = 0.0
    for simulation in simulations:
        if len(simulation.index) < 2:
            continue
        try:
            days = (
                simulation.index[-1] - simulation.index[0]
            ).total_seconds() / 86400.0
        except (AttributeError, TypeError):
            continue
        if days > 0:
            observations += len(simulation.index) - 1
            elapsed_years += days / 365.25
    return observations / elapsed_years if elapsed_years > 0 else 365.25 * 24


def summarize_simulations(simulations: list[EventSimulation]) -> dict:
    """Aggregate sequential test folds without allowing cross-fold trades."""
    if not simulations:
        return {
            "bars": 0,
            "trades": 0,
            "exposure": 0.0,
            "total_return": 0.0,
            "sharpe_annualised": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": None,
            "win_rate": 0.0,
            "expectancy_per_trade": 0.0,
            "average_holding_days": 0.0,
            "by_direction": {
                "BUY": _direction_summary(pd.DataFrame(), "BUY"),
                "SELL": _direction_summary(pd.DataFrame(), "SELL"),
            },
        }

    trade_frames = [simulation.trades for simulation in simulations if not simulation.trades.empty]
    trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    trade_returns = (
        trades["net_return"].to_numpy(dtype=float)
        if not trades.empty
        else np.array([], dtype=float)
    )
    bar_returns = np.concatenate([simulation.bar_returns for simulation in simulations])

    capital = 1.0
    equity_parts = [np.array([capital])]
    for simulation in simulations:
        scaled = simulation.equity_curve * capital
        equity_parts.append(scaled)
        if len(scaled):
            capital = float(scaled[-1])
    equity = np.concatenate(equity_parts)
    peak = np.maximum.accumulate(equity)
    max_drawdown = float((equity / peak - 1.0).min())

    annual_bars = _observed_bars_per_year(simulations)
    std = float(bar_returns.std()) if len(bar_returns) else 0.0
    sharpe = (
        float(bar_returns.mean() / std * np.sqrt(annual_bars)) if std > 0 else 0.0
    )
    total_bars = sum(len(simulation.index) for simulation in simulations)
    active_bars = sum(simulation.active_bars for simulation in simulations)

    return {
        "bars": int(total_bars),
        "trades": int(len(trade_returns)),
        "exposure": float(active_bars / total_bars) if total_bars else 0.0,
        "total_return": float(capital - 1.0),
        "sharpe_annualised": sharpe,
        "max_drawdown": max_drawdown,
        "profit_factor": _profit_factor(trade_returns),
        "win_rate": float((trade_returns > 0).mean()) if len(trade_returns) else 0.0,
        "expectancy_per_trade": float(trade_returns.mean())
        if len(trade_returns)
        else 0.0,
        "average_holding_days": float(trades["holding_days"].mean())
        if not trades.empty
        else 0.0,
        "by_direction": {
            "BUY": _direction_summary(trades, "BUY"),
            "SELL": _direction_summary(trades, "SELL"),
        },
    }


def _select_threshold(
    validation_data: pd.DataFrame,
    predictions: np.ndarray,
    horizon: int,
    granularity: str,
    cost_bps_per_side: float,
    financing_bps_per_day: float,
    thresholds: tuple[float, ...],
    minimum_trades: int,
    direction_mode: str,
    position_filter: np.ndarray | None,
    position_sizes: np.ndarray | None,
    stop_loss_pct: float,
    risk_reward_ratio: float,
    stop_loss_atr_multiplier: float,
    stop_loss_atr_column: str,
) -> tuple[float | None, dict[str, dict]]:
    sweep: dict[str, dict] = {}
    selected: float | None = None
    best_score = 0.0

    for threshold in thresholds:
        simulation = simulate_event_strategy(
            validation_data,
            predictions,
            horizon,
            threshold,
            granularity,
            cost_bps_per_side,
            financing_bps_per_day,
            direction_mode,
            position_filter,
            position_sizes,
            stop_loss_pct,
            risk_reward_ratio,
            stop_loss_atr_multiplier,
            stop_loss_atr_column,
        )
        metrics = summarize_simulations([simulation])
        profit_factor = metrics["profit_factor"]
        eligible = (
            metrics["trades"] >= minimum_trades
            and metrics["total_return"] > 0
            and profit_factor is not None
            and profit_factor > 1.0
            and metrics["sharpe_annualised"] > 0
        )
        sweep[str(threshold)] = {
            "eligible": eligible,
            "trades": metrics["trades"],
            "total_return": metrics["total_return"],
            "sharpe_annualised": metrics["sharpe_annualised"],
            "profit_factor": profit_factor,
        }
        if eligible and metrics["sharpe_annualised"] > best_score:
            best_score = metrics["sharpe_annualised"]
            selected = threshold

    return selected, sweep


def _correlation(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    if len(actual) < 2 or actual.std() == 0 or predicted.std() == 0:
        return None
    return float(np.corrcoef(actual, predicted)[0, 1])


def causal_position_sizes(
    data: pd.DataFrame,
    target_annual_volatility: float | None,
    granularity: str,
    volatility_column: str = "vol_20",
) -> np.ndarray | None:
    """Return causal, unlevered volatility-target position multipliers."""
    if target_annual_volatility is None:
        return None
    if not 0 < target_annual_volatility <= 1:
        raise ValueError("target_annual_volatility must be between zero and one")
    if volatility_column not in data.columns:
        raise ValueError(f"volatility column not found: {volatility_column}")
    annual_bars = 252 * _BARS_PER_DAY.get(granularity, 24)
    realised = data[volatility_column].to_numpy(dtype=float)
    annualised = realised * np.sqrt(annual_bars)
    return np.clip(target_annual_volatility / annualised, 0.0, 1.0)


def calibrate_latest_threshold(
    data: pd.DataFrame,
    feature_columns: list[str],
    horizon: int,
    granularity: str,
    cost_bps_per_side: float,
    financing_bps_per_day: float,
    direction_mode: str,
    target_annual_volatility: float | None,
    stop_loss_pct: float,
    risk_reward_ratio: float,
    stop_loss_atr_multiplier: float,
    validation_fraction: float = 0.2,
    minimum_trades: int = 15,
    thresholds: tuple[float, ...] = EXPECTED_MOVE_THRESHOLDS,
    volatility_column: str = "vol_20",
    stop_loss_atr_column: str = "atr_14",
    model_params: dict | None = None,
) -> dict:
    """Calibrate the deployable threshold on the latest purged validation tail."""
    validation_size = max(240, int(len(data) * validation_fraction))
    train_size = len(data) - validation_size - horizon
    if train_size < max(500, horizon * 10):
        raise ValueError("insufficient data for final threshold calibration")

    train_idx = np.arange(train_size)
    validation_idx = np.arange(train_size + horizon, len(data))
    X = data[feature_columns]
    y = data["_future_return"].to_numpy(dtype=float)
    selector = make_regressor(model_params)
    selector.fit(X.iloc[train_idx], y[train_idx])
    predictions = selector.predict(X.iloc[validation_idx])
    validation_data = data.iloc[validation_idx]
    sizes = causal_position_sizes(
        validation_data,
        target_annual_volatility,
        granularity,
        volatility_column,
    )
    threshold, sweep = _select_threshold(
        validation_data,
        predictions,
        horizon,
        granularity,
        cost_bps_per_side,
        financing_bps_per_day,
        thresholds,
        minimum_trades,
        direction_mode,
        None,
        sizes,
        stop_loss_pct,
        risk_reward_ratio,
        stop_loss_atr_multiplier,
        stop_loss_atr_column,
    )
    simulation = simulate_event_strategy(
        validation_data,
        predictions,
        horizon,
        threshold,
        granularity,
        cost_bps_per_side,
        financing_bps_per_day,
        direction_mode,
        None,
        sizes,
        stop_loss_pct,
        risk_reward_ratio,
        stop_loss_atr_multiplier,
        stop_loss_atr_column,
    )
    return {
        "selected_threshold": threshold,
        "train_range": [str(data.index[train_idx[0]]), str(data.index[train_idx[-1]])],
        "validation_range": [
            str(data.index[validation_idx[0]]),
            str(data.index[validation_idx[-1]]),
        ],
        "selection_sweep": sweep,
        "validation_pnl": summarize_simulations([simulation]),
    }


def _stress_report(
    artifacts: list[dict],
    horizon: int,
    granularity: str,
    cost_bps_per_side: float,
    financing_bps_per_day: float,
    direction_mode: str,
    stop_loss_pct: float,
    risk_reward_ratio: float,
    stop_loss_atr_multiplier: float,
    stop_loss_atr_column: str,
) -> dict:
    simulations = [
        simulate_event_strategy(
            artifact["test_data"],
            artifact["predictions"],
            horizon,
            artifact["threshold"],
            granularity,
            cost_bps_per_side,
            financing_bps_per_day,
            direction_mode,
            artifact["position_filter"],
            artifact["position_sizes"],
            stop_loss_pct,
            risk_reward_ratio,
            stop_loss_atr_multiplier,
            stop_loss_atr_column,
        )
        for artifact in artifacts
    ]
    return {
        "cost_bps_per_side": cost_bps_per_side,
        "financing_bps_per_day": financing_bps_per_day,
        "pnl": summarize_simulations(simulations),
    }


def run_nested_walk_forward(
    data: pd.DataFrame,
    feature_columns: list[str],
    horizon: int = 24,
    n_splits: int = 5,
    granularity: str = "H1",
    cost_bps_per_side: float = 1.5,
    financing_bps_per_day: float = 1.6,
    validation_fraction: float = 0.2,
    minimum_validation_trades: int = 15,
    thresholds: tuple[float, ...] = EXPECTED_MOVE_THRESHOLDS,
    model_params: dict | None = None,
    direction_mode: str = "BOTH",
    position_filter_column: str | None = None,
    target_annual_volatility: float | None = None,
    volatility_column: str = "vol_20",
    stop_loss_pct: float = 0.0,
    risk_reward_ratio: float = 0.0,
    stop_loss_atr_multiplier: float = 0.0,
    stop_loss_atr_column: str = "atr_14",
) -> dict:
    """Run nested expanding-window validation with a purged target horizon."""
    if not 0.1 <= validation_fraction <= 0.4:
        raise ValueError("validation_fraction must be between 0.1 and 0.4")
    if len(data) < 1000:
        raise ValueError("at least 1000 feature rows are required")
    direction_mode = direction_mode.upper()
    if direction_mode not in {"BOTH", "LONG_ONLY", "SHORT_ONLY"}:
        raise ValueError("direction_mode must be BOTH, LONG_ONLY or SHORT_ONLY")
    if position_filter_column is not None and position_filter_column not in data.columns:
        raise ValueError(f"position filter column not found: {position_filter_column}")
    def position_sizes(rows: np.ndarray) -> np.ndarray | None:
        return causal_position_sizes(
            data.iloc[rows],
            target_annual_volatility,
            granularity,
            volatility_column,
        )

    X = data[feature_columns]
    y = data["_future_return"].to_numpy(dtype=float)
    outer = TimeSeriesSplit(n_splits=n_splits, gap=horizon)
    fold_reports: list[dict] = []
    artifacts: list[dict] = []
    importances: list[np.ndarray] = []

    for fold_number, (train_idx, test_idx) in enumerate(outer.split(X), start=1):
        validation_size = max(240, int(len(train_idx) * validation_fraction))
        inner_train_size = len(train_idx) - validation_size - horizon
        if inner_train_size < max(500, horizon * 10):
            raise ValueError(f"fold {fold_number} has insufficient inner training data")

        inner_train_idx = train_idx[:inner_train_size]
        validation_idx = train_idx[inner_train_size + horizon :]
        selector = make_regressor(model_params)
        selector.fit(X.iloc[inner_train_idx], y[inner_train_idx])
        validation_predictions = selector.predict(X.iloc[validation_idx])
        validation_filter = (
            data.iloc[validation_idx][position_filter_column].to_numpy(dtype=bool)
            if position_filter_column is not None
            else None
        )
        validation_sizes = position_sizes(validation_idx)
        threshold, sweep = _select_threshold(
            data.iloc[validation_idx],
            validation_predictions,
            horizon,
            granularity,
            cost_bps_per_side,
            financing_bps_per_day,
            thresholds,
            minimum_validation_trades,
            direction_mode,
            validation_filter,
            validation_sizes,
            stop_loss_pct,
            risk_reward_ratio,
            stop_loss_atr_multiplier,
            stop_loss_atr_column,
        )

        model = make_regressor(model_params)
        model.fit(X.iloc[train_idx], y[train_idx])
        test_predictions = model.predict(X.iloc[test_idx])
        test_filter = (
            data.iloc[test_idx][position_filter_column].to_numpy(dtype=bool)
            if position_filter_column is not None
            else None
        )
        test_sizes = position_sizes(test_idx)
        simulation = simulate_event_strategy(
            data.iloc[test_idx],
            test_predictions,
            horizon,
            threshold,
            granularity,
            cost_bps_per_side,
            financing_bps_per_day,
            direction_mode,
            test_filter,
            test_sizes,
            stop_loss_pct,
            risk_reward_ratio,
            stop_loss_atr_multiplier,
            stop_loss_atr_column,
        )
        pnl = summarize_simulations([simulation])
        importances.append(model.feature_importances_.astype(float))
        artifacts.append(
            {
                "test_data": data.iloc[test_idx],
                "predictions": test_predictions,
                "threshold": threshold,
                "simulation": simulation,
                "position_filter": test_filter,
                "position_sizes": test_sizes,
            }
        )
        fold_reports.append(
            {
                "fold": fold_number,
                "train_range": [str(data.index[train_idx[0]]), str(data.index[train_idx[-1]])],
                "validation_range": [
                    str(data.index[validation_idx[0]]),
                    str(data.index[validation_idx[-1]]),
                ],
                "test_range": [str(data.index[test_idx[0]]), str(data.index[test_idx[-1]])],
                "selected_threshold": threshold,
                "selection_sweep": sweep,
                "prediction_correlation": _correlation(y[test_idx], test_predictions),
                "mean_absolute_error": float(
                    np.mean(np.abs(y[test_idx] - test_predictions))
                ),
                "pnl": pnl,
            }
        )

    base_simulations = [artifact["simulation"] for artifact in artifacts]
    aggregate = summarize_simulations(base_simulations)
    double_costs = _stress_report(
        artifacts,
        horizon,
        granularity,
        cost_bps_per_side * 2.0,
        financing_bps_per_day * 2.0,
        direction_mode,
        stop_loss_pct,
        risk_reward_ratio,
        stop_loss_atr_multiplier,
        stop_loss_atr_column,
    )
    severe_costs = _stress_report(
        artifacts,
        horizon,
        granularity,
        max(cost_bps_per_side, 5.0),
        max(financing_bps_per_day, 3.2),
        direction_mode,
        stop_loss_pct,
        risk_reward_ratio,
        stop_loss_atr_multiplier,
        stop_loss_atr_column,
    )

    profitable_folds = sum(report["pnl"]["total_return"] > 0 for report in fold_reports)
    losing_folds = sum(report["pnl"]["total_return"] < 0 for report in fold_reports)
    flat_folds = n_splits - profitable_folds - losing_folds
    severe_pnl = severe_costs["pnl"]
    checks = {
        "positive_aggregate_return": aggregate["total_return"] > 0,
        "sharpe_at_least_one": aggregate["sharpe_annualised"] >= 1.0,
        "profit_factor_at_least_1_2": aggregate["profit_factor"] is not None
        and aggregate["profit_factor"] >= 1.2,
        "max_drawdown_not_below_25pct": aggregate["max_drawdown"] >= -0.25,
        "at_least_60pct_profitable_folds": profitable_folds / n_splits >= 0.6,
        "minimum_100_trades": aggregate["trades"] >= 100,
        "positive_under_severe_costs": severe_pnl["total_return"] > 0
        and severe_pnl["profit_factor"] is not None
        and severe_pnl["profit_factor"] > 1.0,
    }
    decision = (
        "PROMOTE_TO_PAPER_TRADING"
        if all(checks.values())
        else "RESEARCH_ONLY_NOT_ROBUST"
    )

    mean_importance = np.mean(np.vstack(importances), axis=0)
    ranked_features = sorted(
        zip(feature_columns, mean_importance, strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    importance_total = float(mean_importance.sum())

    return {
        "mode": "READ_ONLY_RESEARCH",
        "strategy": (
            f"direct_{horizon}bar_expected_return_regression_"
            f"{direction_mode.lower()}"
        ),
        "samples": int(len(data)),
        "evaluated": int(sum(len(artifact["test_data"]) for artifact in artifacts)),
        "params": {
            "horizon": horizon,
            "folds": n_splits,
            "granularity": granularity,
            "cost_bps_per_side": cost_bps_per_side,
            "financing_bps_per_day": financing_bps_per_day,
            "validation_fraction": validation_fraction,
            "minimum_validation_trades": minimum_validation_trades,
            "thresholds": list(thresholds),
            "embargo_bars": horizon,
            "direction_mode": direction_mode,
            "position_filter_column": position_filter_column,
            "target_annual_volatility": target_annual_volatility,
            "volatility_column": volatility_column
            if target_annual_volatility is not None
            else None,
            "stop_loss_pct": stop_loss_pct or None,
            "risk_reward_ratio": risk_reward_ratio
            if stop_loss_pct or stop_loss_atr_multiplier
            else None,
            "stop_loss_atr_multiplier": stop_loss_atr_multiplier or None,
            "stop_loss_atr_column": stop_loss_atr_column
            if stop_loss_atr_multiplier
            else None,
        },
        "aggregate": aggregate,
        "folds": fold_reports,
        "cost_stress": {
            "double_costs": double_costs,
            "severe_costs": severe_costs,
        },
        "top_features": [
            {
                "feature": feature,
                "relative_importance": float(importance / importance_total)
                if importance_total > 0
                else 0.0,
            }
            for feature, importance in ranked_features[:15]
        ],
        "robustness": {
            "profitable_folds": profitable_folds,
            "losing_folds": losing_folds,
            "flat_folds": flat_folds,
            "checks": checks,
            "decision": decision,
            "live_integration": "DISABLED",
            "requires_forward_paper_validation": True,
            "multiple_testing_warning": (
                "Candidate variants were compared on the available history; "
                "future paper results are required before any live decision."
            ),
        },
    }
