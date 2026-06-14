"""3-class labelling: hausse / baisse / consolidation.

The target is the sign of the forward return over `horizon` bars: UP if it
exceeds +threshold, DOWN if below -threshold, FLAT in between. The last
`horizon` bars have no known future and are left unlabelled (NaN).
"""

import pandas as pd

DOWN, FLAT, UP = 0, 1, 2
CLASS_NAMES = {DOWN: "DOWN", FLAT: "FLAT", UP: "UP"}


def make_labels(
    close: pd.Series, horizon: int = 12, threshold: float = 0.001
) -> tuple[pd.Series, pd.Series]:
    fwd_ret = close.shift(-horizon) / close - 1
    label = pd.Series(FLAT, index=close.index, dtype="float64")
    label[fwd_ret > threshold] = UP
    label[fwd_ret < -threshold] = DOWN
    # No future available for the final `horizon` bars.
    label.iloc[-horizon:] = pd.NA
    return label, fwd_ret
