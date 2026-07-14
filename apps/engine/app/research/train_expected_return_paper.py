"""Train the validated expected-return candidate into a paper-only artifact."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib

from app.config import get_settings
from app.research.dataset import load_candles
from app.research.expected_return import (
    build_expected_return_dataset,
    calibrate_latest_threshold,
    make_regressor,
    run_nested_walk_forward,
)

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train expected-return paper model")
    parser.add_argument("--granularity", default="H1")
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--cost-bps-per-side", type=float, default=1.5)
    parser.add_argument("--financing-bps-per-day", type=float, default=1.6)
    parser.add_argument("--target-annual-volatility", type=float, default=0.15)
    parser.add_argument("--stop-loss-pct", type=float, default=0.005)
    parser.add_argument("--stop-loss-atr-multiplier", type=float, default=3.0)
    parser.add_argument("--risk-reward-ratio", type=float, default=3.0)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    candles = asyncio.run(load_candles(settings, args.granularity))
    if candles.empty or len(candles) < 1000:
        raise SystemExit(f"Donnees insuffisantes ({len(candles)} bougies)")

    data, feature_columns = build_expected_return_dataset(candles, args.horizon)
    common = {
        "horizon": args.horizon,
        "granularity": args.granularity,
        "cost_bps_per_side": args.cost_bps_per_side,
        "financing_bps_per_day": args.financing_bps_per_day,
        "direction_mode": "LONG_ONLY",
        "target_annual_volatility": args.target_annual_volatility,
        "stop_loss_pct": args.stop_loss_pct,
        "risk_reward_ratio": args.risk_reward_ratio,
        "stop_loss_atr_multiplier": args.stop_loss_atr_multiplier,
    }
    report = run_nested_walk_forward(
        data,
        feature_columns,
        n_splits=args.folds,
        **common,
    )
    if report["robustness"]["decision"] != "PROMOTE_TO_PAPER_TRADING":
        raise SystemExit(
            "Refus d'ecrire l'artefact: la validation ne permet pas le paper trading"
        )

    calibration = calibrate_latest_threshold(data, feature_columns, **common)
    threshold = calibration["selected_threshold"]
    if threshold is None:
        raise SystemExit("Refus d'ecrire l'artefact: aucun seuil recent eligible")

    model = make_regressor()
    model.fit(data[feature_columns], data["_future_return"].to_numpy(dtype=float))
    output_dir = args.output_dir or (
        MODELS_DIR / args.granularity / "expected_return_paper"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    version = "paper-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    meta = {
        "model_kind": "expected_return_regressor",
        "model_version": version,
        "paper_only": True,
        "live_eligible": False,
        "feature_cols": feature_columns,
        "granularity": args.granularity,
        "horizon_bars": args.horizon,
        "direction_mode": "LONG_ONLY",
        "expected_return_threshold": threshold,
        "target_annual_volatility": args.target_annual_volatility,
        "volatility_column": "vol_20",
        "stop_loss_floor_pct": args.stop_loss_pct,
        "stop_loss_atr_multiplier": args.stop_loss_atr_multiplier,
        "stop_loss_atr_column": "atr_14",
        "risk_reward_ratio": args.risk_reward_ratio,
        "cost_bps_per_side": args.cost_bps_per_side,
        "financing_bps_per_day": args.financing_bps_per_day,
        "paper_validation_min_closed_trades": settings.paper_validation_min_trades,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_samples": int(len(data)),
        "training_range": [str(data.index[0]), str(data.index[-1])],
    }
    joblib.dump(model, output_dir / "model.joblib")
    (output_dir / "meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    (output_dir / "report.json").write_text(
        json.dumps({"walk_forward": report, "latest_calibration": calibration}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output_dir": str(output_dir), "meta": meta}, indent=2))


if __name__ == "__main__":
    main()
