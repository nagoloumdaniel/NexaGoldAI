"""Read-only CLI for nested validation of the expected-return strategy.

Usage:
  .venv/Scripts/python.exe -m app.research.validate_expected_return --granularity H1
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.research.dataset import load_candles
from app.research.expected_return import (
    build_completed_daily_momentum_filter,
    build_expected_return_dataset,
    run_nested_walk_forward,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validation imbriquee read-only de la strategie de rendement attendu"
    )
    parser.add_argument("--granularity", default="H1")
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--cost-bps-per-side", type=float, default=1.5)
    parser.add_argument("--financing-bps-per-day", type=float, default=1.6)
    parser.add_argument("--minimum-validation-trades", type=int, default=15)
    parser.add_argument(
        "--direction-mode",
        choices=("BOTH", "LONG_ONLY", "SHORT_ONLY"),
        default="BOTH",
    )
    parser.add_argument("--trend-lookback-days", type=int, default=0)
    parser.add_argument("--target-annual-volatility", type=float, default=0.0)
    parser.add_argument("--stop-loss-pct", type=float, default=0.0)
    parser.add_argument("--risk-reward-ratio", type=float, default=1.5)
    parser.add_argument("--stop-loss-atr-multiplier", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    candles = asyncio.run(load_candles(settings, args.granularity))
    if candles.empty or len(candles) < 1000:
        print(json.dumps({"error": f"Donnees insuffisantes ({len(candles)} bougies)"}))
        return

    data, feature_columns = build_expected_return_dataset(candles, args.horizon)
    position_filter_column = None
    if args.trend_lookback_days:
        position_filter_column = "_daily_momentum_allowed"
        data[position_filter_column] = build_completed_daily_momentum_filter(
            candles, args.trend_lookback_days
        ).reindex(data.index)
        data = data.dropna(subset=[position_filter_column])
    report = run_nested_walk_forward(
        data,
        feature_columns,
        horizon=args.horizon,
        n_splits=args.folds,
        granularity=args.granularity,
        cost_bps_per_side=args.cost_bps_per_side,
        financing_bps_per_day=args.financing_bps_per_day,
        minimum_validation_trades=args.minimum_validation_trades,
        direction_mode=args.direction_mode,
        position_filter_column=position_filter_column,
        target_annual_volatility=args.target_annual_volatility or None,
        stop_loss_pct=args.stop_loss_pct,
        risk_reward_ratio=args.risk_reward_ratio,
        stop_loss_atr_multiplier=args.stop_loss_atr_multiplier,
    )
    report["params"]["trend_lookback_days"] = args.trend_lookback_days or None
    report["data_range"] = [str(candles.index[0]), str(candles.index[-1])]
    report["candles"] = int(len(candles))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
