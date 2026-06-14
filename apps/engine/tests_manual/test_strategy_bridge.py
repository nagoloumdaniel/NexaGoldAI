"""Smoke test of the phase 2 -> phase 3 bridge: load the saved LightGBM model
and turn a batch of candles from the DB into a Signal.

Run: .venv\\Scripts\\python.exe -m tests_manual.test_strategy_bridge
"""

import asyncio
from pathlib import Path

from app.config import get_settings
from app.research.dataset import load_candles
from app.strategy.base import Action
from app.strategy.lightgbm_strategy import LightGBMStrategy

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "M5"


def main() -> None:
    settings = get_settings()
    df = asyncio.run(load_candles(settings, "M5"))
    # Feed the last 120 candles as the engine would at decision time.
    candles = [
        {
            "time": ts.isoformat(),
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
        }
        for ts, row in df.tail(120).iterrows()
    ]

    strategy = LightGBMStrategy(MODEL_DIR)
    signal = strategy.evaluate(candles)

    assert isinstance(signal.action, Action), signal
    assert 0.0 <= signal.confidence <= 1.0, signal
    assert signal.features, "features attendues dans le signal"
    print(
        f"OK: action={signal.action.value} confidence={signal.confidence:.3f} "
        f"reason={signal.reason!r} ({len(signal.features)} features)"
    )


if __name__ == "__main__":
    main()
