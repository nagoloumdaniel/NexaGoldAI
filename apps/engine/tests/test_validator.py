"""Tests du validateur de qualité des données de marché."""

from datetime import datetime, timedelta, timezone

from app.data.validator import validate_candles

# Mardi 2026-07-28 12:00 UTC : marché or ouvert.
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def make_candles(count: int, start: datetime | None = None, step_minutes: int = 5,
                 price: float = 3300.0, drift: float = 0.5) -> list[dict]:
    start = start or NOW - timedelta(minutes=step_minutes * count)
    out = []
    for i in range(count):
        o = price + i * drift
        c = o + drift
        out.append(
            {
                "time": (start + timedelta(minutes=step_minutes * i)).isoformat(),
                "open": o,
                "high": max(o, c) + 0.3,
                "low": min(o, c) - 0.3,
                "close": c,
                "volume": 100 + i,
            }
        )
    return out


def test_clean_series_scores_high():
    report = validate_candles(make_candles(100), "M5", now=NOW)
    assert report["valid"] is True
    assert report["score"] >= 0.99
    assert report["missing_bars"] == 0
    assert report["malformed"] == 0
    assert report["stale"] is False


def test_empty_and_unknown_granularity():
    assert validate_candles([], "M5", now=NOW)["valid"] is False
    assert validate_candles(make_candles(10), "M7", now=NOW)["valid"] is False


def test_detects_weekday_gap():
    candles = make_candles(60)
    removed = candles[:30] + candles[33:]  # 3 bougies manquantes en semaine
    report = validate_candles(removed, "M5", now=NOW)
    assert report["missing_bars"] == 3
    assert report["gap_events"] == 1
    assert any(i["kind"] == "GAP" for i in report["issues"])


def test_weekend_gap_is_not_a_data_gap():
    # Vendredi 20:55 UTC -> dimanche 23:00 UTC : fermeture hebdomadaire.
    friday_end = datetime(2026, 7, 24, 19, 0, tzinfo=timezone.utc)
    before = make_candles(24, start=friday_end)  # jusqu'à ~21:00 vendredi
    sunday = datetime(2026, 7, 26, 23, 0, tzinfo=timezone.utc)
    after = make_candles(24, start=sunday)
    report = validate_candles(
        before + after, "M5", now=sunday + timedelta(minutes=5 * 24)
    )
    assert report["missing_bars"] == 0
    assert report["gap_events"] == 0


def test_detects_malformed_candles():
    candles = make_candles(50)
    candles[10]["high"] = candles[10]["low"] - 1.0  # high < low
    candles[20]["close"] = -5.0  # prix négatif
    report = validate_candles(candles, "M5", now=NOW)
    assert report["malformed"] == 2
    assert report["score"] < 1.0


def test_detects_duplicates_and_out_of_order():
    candles = make_candles(50)
    candles[6]["time"] = candles[5]["time"]  # doublon
    candles[30], candles[31] = candles[31], candles[30]  # inversion
    report = validate_candles(candles, "M5", now=NOW)
    assert report["duplicates"] == 1
    assert report["out_of_order"] >= 1


def test_detects_frozen_data():
    candles = make_candles(40)
    for c in candles[15:30]:  # 15 bougies OHLC identiques
        c["open"], c["high"], c["low"], c["close"] = 3300.0, 3300.5, 3299.5, 3300.0
    report = validate_candles(candles, "M5", now=NOW)
    assert report["frozen"] is True
    assert report["longest_frozen_run"] >= 15
    assert report["score"] <= 0.7


def test_detects_stale_data_when_market_open():
    old = make_candles(50, start=NOW - timedelta(hours=5))
    report = validate_candles(old, "M5", now=NOW)
    assert report["stale"] is True
    assert report["valid"] is False


def test_no_staleness_flag_during_weekend():
    saturday = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    candles = make_candles(50, start=saturday - timedelta(hours=16))
    report = validate_candles(candles, "M5", now=saturday)
    assert report["stale"] is False


def test_accepts_datetime_objects_from_db():
    candles = make_candles(30)
    for c in candles:  # la DB renvoie des datetime naïfs UTC, pas des chaînes
        c["time"] = datetime.fromisoformat(c["time"]).replace(tzinfo=None)
    report = validate_candles(candles, "M5", now=NOW)
    assert report["valid"] is True
