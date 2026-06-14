"""Deterministic check of the Dukascopy bi5 parser/aggregator (no network).

Builds a synthetic bi5 payload with known ticks, then asserts parse_ticks and
aggregate_ticks reconstruct the expected prices and candle.
Run: .venv\\Scripts\\python.exe -m tests_manual.test_dukascopy_parse
"""

import lzma
import struct
from datetime import datetime

from app.data.dukascopy import aggregate_ticks, parse_ticks

DIVISOR = 1000.0
TICK = struct.Struct(">iiiff")
HOUR = datetime(2026, 6, 10, 13, 0, 0)

# Three ticks within the hour: (ms, ask_points, bid_points, ask_vol, bid_vol)
raw_ticks = [
    (0, 4219000, 4218000, 1.0, 1.0),       # mid 4218.5
    (60_000, 4221000, 4220000, 1.0, 1.0),  # mid 4220.5  (high)
    (120_000, 4217000, 4216000, 1.0, 1.0), # mid 4216.5  (low, close)
]
payload = b"".join(TICK.pack(*t) for t in raw_ticks)
compressed = lzma.compress(payload, format=lzma.FORMAT_ALONE)

ticks = parse_ticks(compressed, HOUR, DIVISOR)
assert len(ticks) == 3, f"attendu 3 ticks, obtenu {len(ticks)}"
# First tick: bid 4218.0 / ask 4219.0
assert abs(ticks[0][1] - 4218.0) < 1e-9, ticks[0]
assert abs(ticks[0][2] - 4219.0) < 1e-9, ticks[0]

# All three ticks fall in the same M5 bucket (13:00).
candles = aggregate_ticks(ticks, "M5")
assert len(candles) == 1, f"attendu 1 bougie M5, obtenu {len(candles)}"
c = candles[0]
assert c["time"] == "2026-06-10T13:00:00", c["time"]
assert abs(c["open"] - 4218.5) < 1e-9, c
assert abs(c["high"] - 4220.5) < 1e-9, c
assert abs(c["low"] - 4216.5) < 1e-9, c
assert abs(c["close"] - 4216.5) < 1e-9, c
assert c["volume"] == 3, c

# Same ticks at M1 fall in three distinct buckets (13:00, 13:01, 13:02).
m1 = aggregate_ticks(ticks, "M1")
assert len(m1) == 3, f"attendu 3 bougies M1, obtenu {len(m1)}"
assert all(c["volume"] == 1 for c in m1), m1

print("OK: parse_ticks + aggregate_ticks valides")
