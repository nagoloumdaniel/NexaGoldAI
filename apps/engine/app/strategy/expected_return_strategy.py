"""Paper-only expected-return regression strategy."""

import json
from pathlib import Path

import joblib
import numpy as np

from app.research.dataset import candles_to_frame
from app.research.features import build_features
from app.strategy.base import Action, Signal, Strategy

_BARS_PER_DAY = {"M1": 1440, "M5": 288, "M15": 96, "M30": 48, "H1": 24, "H4": 6, "D1": 1}


class ExpectedReturnPaperStrategy(Strategy):
    name = "expected-return-paper"
    paper_only = True

    def __init__(self, model_dir: str | Path, configured_granularity: str):
        model_dir = Path(model_dir)
        self._model = joblib.load(model_dir / "model.joblib")
        self._meta = json.loads(
            (model_dir / "meta.json").read_text(encoding="utf-8")
        )
        if self._meta.get("model_kind") != "expected_return_regressor":
            raise ValueError("Unexpected model kind for expected-return strategy")
        if self._meta.get("paper_only") is not True:
            raise ValueError("Expected-return artifact is not marked paper-only")
        if self._meta.get("live_eligible") is not False:
            raise ValueError("Expected-return artifact must explicitly reject live use")
        if self._meta.get("granularity") != configured_granularity:
            raise ValueError("Configured granularity does not match paper artifact")

        self._feature_cols = list(self._meta["feature_cols"])
        self._granularity = configured_granularity
        self._horizon = int(self._meta["horizon_bars"])
        self._threshold = float(self._meta["expected_return_threshold"])
        self._target_volatility = float(self._meta["target_annual_volatility"])
        self._volatility_column = str(self._meta["volatility_column"])
        self._stop_floor = float(self._meta["stop_loss_floor_pct"])
        self._stop_atr_multiplier = float(self._meta["stop_loss_atr_multiplier"])
        self._stop_atr_column = str(self._meta["stop_loss_atr_column"])
        self._risk_reward = float(self._meta["risk_reward_ratio"])
        self._cost_bps_per_side = float(self._meta["cost_bps_per_side"])
        self._financing_bps_per_day = float(self._meta["financing_bps_per_day"])
        self.paper_horizon_hours = round(
            self._horizon * 24 / _BARS_PER_DAY.get(self._granularity, 24)
        )

    @property
    def model_version(self) -> str:
        return str(self._meta["model_version"])

    @property
    def stop_loss_floor_pct(self) -> float:
        return self._stop_floor

    @property
    def stop_loss_atr_multiplier(self) -> float:
        return self._stop_atr_multiplier

    @property
    def risk_reward_ratio(self) -> float:
        return self._risk_reward

    def evaluate(
        self, candles: list[dict], macro_candles: list[dict] | None = None
    ) -> Signal:
        frame = candles_to_frame(candles)
        if frame.empty:
            return Signal(Action.HOLD, 0.0, "Aucune bougie fournie")

        features = build_features(frame)
        latest = features.iloc[[-1]][self._feature_cols]
        if latest.isna().any(axis=1).iloc[0]:
            return Signal(
                Action.HOLD,
                0.0,
                "Features incompletes pour le modele expected-return",
            )

        expected_return = float(self._model.predict(latest)[0])
        realised_bar_volatility = float(latest.iloc[0][self._volatility_column])
        annual_bars = 252 * _BARS_PER_DAY.get(self._granularity, 24)
        realised_annual_volatility = realised_bar_volatility * np.sqrt(annual_bars)
        if not np.isfinite(realised_annual_volatility) or realised_annual_volatility <= 0:
            return Signal(Action.HOLD, 0.0, "Volatilite realisee invalide")

        position_size = float(
            np.clip(self._target_volatility / realised_annual_volatility, 0.0, 1.0)
        )
        atr_pct = float(latest.iloc[0][self._stop_atr_column])
        stop_loss_pct = max(self._stop_floor, atr_pct * self._stop_atr_multiplier)
        holding_days = self._horizon / _BARS_PER_DAY.get(self._granularity, 24)
        expected_cost = (
            2.0 * self._cost_bps_per_side
            + holding_days * self._financing_bps_per_day
        ) / 1e4
        expected_value_after_costs = expected_return - expected_cost
        edge_score = float(
            np.clip(expected_return / max(2.0 * self._threshold, 1e-12), 0.0, 1.0)
        )
        decision_features = latest.iloc[0].to_dict()
        decision_features.update(
            {
                "signal_kind": "expected_return",
                "confidence_kind": "edge_ratio_not_probability",
                "expected_return": expected_return,
                "expected_return_threshold": self._threshold,
                "expected_value_after_costs": expected_value_after_costs,
                "estimated_cost_return": expected_cost,
                "position_size": position_size,
                "target_annual_volatility": self._target_volatility,
                "realised_annual_volatility": realised_annual_volatility,
                "stop_loss_pct": stop_loss_pct,
                "stop_loss_atr_multiplier": self._stop_atr_multiplier,
                "risk_reward_ratio": self._risk_reward,
                "horizon_bars": self._horizon,
                "horizon_hours": self.paper_horizon_hours,
                "decision_bar_time": str(frame.index[-1]),
                "model_version": self.model_version,
                "paper_only": True,
            }
        )

        if expected_return < self._threshold:
            return Signal(
                Action.HOLD,
                edge_score,
                (
                    f"Expected return {expected_return:.4%} sous le seuil "
                    f"{self._threshold:.4%}"
                ),
                decision_features,
                position_size,
            )

        return Signal(
            Action.BUY,
            edge_score,
            (
                f"Expected return {expected_return:.4%} >= {self._threshold:.4%}; "
                f"exposition {position_size:.1%}; stop {stop_loss_pct:.2%}"
            ),
            decision_features,
            position_size,
        )
