"""Strategy contract.

Every strategy (rule-based, LightGBM, RL agent...) implements the same
interface so the engine can run, compare and swap them without code changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    action: Action
    # 0.0 to 1.0 — strategies must be honest about uncertainty; the risk
    # manager can ignore low-confidence signals.
    confidence: float
    # Human-readable explanation, stored with every trade for the dashboard
    # ("Raisons de la décision IA" in the spec).
    reason: str
    # Feature values used for the decision, kept for retraining datasets.
    features: dict = field(default_factory=dict)


class Strategy(ABC):
    """A strategy turns recent candles into a trading signal. It never talks
    to the broker directly — execution and risk are the engine's job."""

    name: str = "base"
    # Whether evaluate() needs the macro candles (the Trader fetches them on demand).
    needs_macro: bool = False

    @abstractmethod
    def evaluate(
        self, candles: list[dict], macro_candles: list[dict] | None = None
    ) -> Signal:
        """candles: chronological OHLCV dicts. macro_candles: same shape for the
        correlated macro instrument, supplied only when needs_macro is True."""
        raise NotImplementedError


class AlwaysHold(Strategy):
    """Placeholder strategy used until the first real model is trained.
    Keeps the whole pipeline runnable end to end without taking positions."""

    name = "always-hold"

    def evaluate(
        self, candles: list[dict], macro_candles: list[dict] | None = None
    ) -> Signal:
        return Signal(
            action=Action.HOLD,
            confidence=1.0,
            reason="Placeholder strategy: no model trained yet.",
        )
