"""Deterministic check of triple-barrier labelling (no network/DB).

Run: .venv\\Scripts\\python.exe -m tests_manual.test_labeling
"""

import pandas as pd

from app.research.labeling import DOWN, UP, make_labels

# Oscillating base so rolling volatility is non-zero everywhere.
base = [100.0, 100.1, 99.9, 100.05, 99.95, 100.05, 99.95, 100.05, 99.95, 100.05,
        99.95, 100.05]
high = list(base)
low = list(base)

# Inject an unmistakable up move within the horizon of bar 4...
high[5] = 200.0
# ...and an unmistakable down move within the horizon of bar 6.
low[7] = 50.0

df = pd.DataFrame({"open": base, "high": high, "low": low, "close": base})
labels = make_labels(
    df,
    {"labeling": "triple_barrier", "horizon": 2, "vol_mult": 1.0, "vol_window": 3},
)

assert labels.iloc[4] == UP, f"bar 4 attendu UP, obtenu {labels.iloc[4]}"
assert labels.iloc[6] == DOWN, f"bar 6 attendu DOWN, obtenu {labels.iloc[6]}"
# The final `horizon` bars have no full future window -> unlabelled.
assert pd.isna(labels.iloc[-1]) and pd.isna(labels.iloc[-2])

print("OK: triple-barrier valide")
