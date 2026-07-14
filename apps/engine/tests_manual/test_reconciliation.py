"""Deterministic checks for broker reconciliation helpers (no network/DB).

Run: .venv\\Scripts\\python.exe -m tests_manual.test_reconciliation
"""

from app.execution.trader import _compute_pnl, _extract_deal_id, _parse_broker_time


assert _extract_deal_id({"affectedDeals": [{"dealId": "abc"}]}) == "abc"
assert _extract_deal_id({"affectedDeals": []}) is None

assert _compute_pnl("BUY", 2.0, 100.0, 105.0) == 10.0
assert _compute_pnl("SELL", 2.0, 100.0, 95.0) == 10.0
assert _compute_pnl("BUY", 2.0, 100.0, 95.0) == -10.0
assert _compute_pnl("SELL", 2.0, 100.0, 105.0) == -10.0

dt = _parse_broker_time("2022-01-03T15:01:48.420")
assert dt is not None and dt.tzinfo is not None

print("OK: reconciliation helpers valides")
