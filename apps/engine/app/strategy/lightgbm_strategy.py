"""LightGBM strategy — loads a model trained by app.research.run and turns the
latest candles into a trading signal. This is the bridge from phase 2
(research) to phase 3 (paper trading): same Strategy interface as AlwaysHold.
"""

import json
from pathlib import Path

import joblib

from app.research.dataset import candles_to_frame
from app.research.features import build_features
from app.research.labeling import DOWN, FLAT, UP
from app.strategy.base import Action, Signal, Strategy

_ACTION = {UP: Action.BUY, DOWN: Action.SELL, FLAT: Action.HOLD}


class LightGBMStrategy(Strategy):
    name = "lightgbm"

    def __init__(self, model_dir: str | Path):
        model_dir = Path(model_dir)
        self._model = joblib.load(model_dir / "model.joblib")
        meta = json.loads((model_dir / "meta.json").read_text(encoding="utf-8"))
        self._feature_cols = meta["feature_cols"]
        # Confidence filter learned at training time: below it, stay flat.
        self._confidence_threshold = float(meta.get("confidence_threshold", 0.0))
        # Does this model use macro features?
        self.needs_macro = bool(meta.get("config", {}).get("macro"))

    def evaluate(
        self, candles: list[dict], macro_candles: list[dict] | None = None
    ) -> Signal:
        df = candles_to_frame(candles)
        if df.empty:
            return Signal(Action.HOLD, 0.0, "Aucune bougie fournie")

        macro_df = None
        if self.needs_macro:
            macro_df = candles_to_frame(macro_candles or [])
            if macro_df.empty:
                return Signal(
                    Action.HOLD, 0.0, "Macro indisponible — pas de trade (sécurité)"
                )

        features = build_features(df, macro_df)
        latest = features.iloc[[-1]][self._feature_cols]
        if latest.isna().any(axis=1).iloc[0]:
            return Signal(
                Action.HOLD,
                0.0,
                "Features incomplètes (pas assez d'historique récent)",
            )

        proba = self._model.predict_proba(latest)[0]
        best = int(proba.argmax())
        predicted_class = int(self._model.classes_[best])
        confidence = float(proba[best])
        action = _ACTION[predicted_class]
        features = latest.iloc[0].to_dict()

        # Below the learned confidence threshold, don't trade (stay flat).
        if action != Action.HOLD and confidence < self._confidence_threshold:
            return Signal(
                action=Action.HOLD,
                confidence=confidence,
                reason=(
                    f"LightGBM: {action.value} ignoré "
                    f"(p={confidence:.2f} < seuil {self._confidence_threshold:.2f})"
                ),
                features=features,
            )

        return Signal(
            action=action,
            confidence=confidence,
            reason=f"LightGBM: {action.value} (p={confidence:.2f})",
            features=features,
        )
