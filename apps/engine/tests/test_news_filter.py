"""Tests du filtre d'annonces économiques (fail-closed)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.fundamental.calendar import (
    HIGH,
    LOW,
    MEDIUM,
    CalendarEvent,
    EconomicCalendarProvider,
    NewsFilter,
    parse_forex_factory,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def make_settings(**overrides) -> Settings:
    base = dict(
        news_filter_enabled=True,
        news_currencies="USD",
        news_block_high_pre_minutes=30,
        news_block_high_post_minutes=20,
        news_block_medium_pre_minutes=10,
        news_block_medium_post_minutes=10,
        news_refresh_minutes=60,
        news_max_age_minutes=360,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


class FakeProvider(EconomicCalendarProvider):
    name = "fake"

    def __init__(self, events=None, fail=False):
        self.events = events or []
        self.fail = fail
        self.calls = 0

    async def fetch_events(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider down")
        return self.events


def event(minutes_from_now: int, impact: str = HIGH, currency: str = "USD"):
    return CalendarEvent(
        time=NOW + timedelta(minutes=minutes_from_now),
        currency=currency,
        impact=impact,
        title="Test event",
    )


@pytest.mark.asyncio
async def test_disabled_filter_never_blocks():
    f = NewsFilter(make_settings(news_filter_enabled=False), FakeProvider(fail=True))
    verdict = await f.check(NOW)
    assert verdict["blocked"] is False


@pytest.mark.asyncio
async def test_fail_closed_when_provider_never_succeeded():
    f = NewsFilter(make_settings(), FakeProvider(fail=True))
    verdict = await f.check(NOW)
    assert verdict["blocked"] is True
    assert "fail-closed" in verdict["reason"]


@pytest.mark.asyncio
async def test_fail_closed_when_cache_too_old():
    provider = FakeProvider(events=[])
    f = NewsFilter(make_settings(), provider)
    assert (await f.check(NOW))["blocked"] is False  # cache frais, aucune annonce

    # Le provider tombe en panne ; au-delà de l'âge maximal => blocage.
    provider.fail = True
    later = NOW + timedelta(minutes=361)
    verdict = await f.check(later)
    assert verdict["blocked"] is True
    assert "trop ancien" in verdict["reason"]


@pytest.mark.asyncio
async def test_blocks_inside_high_impact_window():
    f = NewsFilter(make_settings(), FakeProvider(events=[event(+25, HIGH)]))
    verdict = await f.check(NOW)  # 25 min avant, fenêtre pre=30
    assert verdict["blocked"] is True
    assert "HIGH" in verdict["reason"]

    # 15 min après l'annonce (fenêtre post=20) : toujours bloqué.
    f2 = NewsFilter(make_settings(), FakeProvider(events=[event(-15, HIGH)]))
    assert (await f2.check(NOW))["blocked"] is True


@pytest.mark.asyncio
async def test_allows_outside_windows():
    events = [event(+45, HIGH), event(-25, HIGH), event(+15, LOW)]
    f = NewsFilter(make_settings(), FakeProvider(events=events))
    verdict = await f.check(NOW)
    assert verdict["blocked"] is False


@pytest.mark.asyncio
async def test_medium_impact_uses_shorter_windows():
    # 15 min avant une annonce MEDIUM (fenêtre pre=10) : autorisé.
    f = NewsFilter(make_settings(), FakeProvider(events=[event(+15, MEDIUM)]))
    assert (await f.check(NOW))["blocked"] is False
    # 5 min avant : bloqué.
    f2 = NewsFilter(make_settings(), FakeProvider(events=[event(+5, MEDIUM)]))
    assert (await f2.check(NOW))["blocked"] is True


@pytest.mark.asyncio
async def test_ignores_other_currencies():
    f = NewsFilter(make_settings(), FakeProvider(events=[event(+5, HIGH, "EUR")]))
    assert (await f.check(NOW))["blocked"] is False


@pytest.mark.asyncio
async def test_refresh_respects_interval_and_keeps_cache_on_failure():
    provider = FakeProvider(events=[event(+300, HIGH)])
    f = NewsFilter(make_settings(), provider)
    await f.check(NOW)
    await f.check(NOW + timedelta(minutes=10))
    assert provider.calls == 1  # pas de re-fetch avant refresh_minutes

    provider.fail = True
    verdict = await f.check(NOW + timedelta(minutes=70))  # re-fetch échoue
    assert provider.calls == 2
    # Cache conservé et encore sous l'âge maximal : pas de blocage.
    assert verdict["blocked"] is False


def test_parse_forex_factory_defensive():
    payload = [
        {
            "title": "Non-Farm Employment Change",
            "country": "USD",
            "date": "2026-07-31T08:30:00-04:00",
            "impact": "High",
        },
        {"title": "Bank Holiday", "country": "USD", "date": "2026-07-28T00:00:00-04:00", "impact": "Holiday"},
        {"title": "Sans date", "country": "USD", "impact": "High"},
        {"title": "Date invalide", "country": "USD", "date": "n/a", "impact": "High"},
        "pas un dict",
        {"title": "CPI y/y", "country": "EUR", "date": "2026-07-30T09:00:00", "impact": "medium"},
    ]
    events = parse_forex_factory(payload)
    assert len(events) == 2
    nfp = events[0]
    assert nfp.currency == "USD"
    assert nfp.impact == HIGH
    # 08:30 heure de New York (UTC-4) => 12:30 UTC.
    assert nfp.time == datetime(2026, 7, 31, 12, 30, tzinfo=timezone.utc)
    # Date sans offset : supposée UTC (hypothèse conservatrice).
    assert events[1].time.tzinfo is not None
    assert events[1].impact == MEDIUM


def test_upcoming_lists_relevant_events_sorted():
    f = NewsFilter(make_settings(), FakeProvider())
    f._events = [  # noqa: SLF001 — injection directe pour le test
        event(+120, HIGH),
        event(+30, MEDIUM),
        event(+60, LOW),
        event(+90, HIGH, "EUR"),
        event(+60 * 40, HIGH),  # au-delà de 24 h
    ]
    upcoming = f.upcoming(NOW)
    assert len(upcoming) == 2
    assert upcoming[0]["impact"] == MEDIUM
    assert upcoming[1]["impact"] == HIGH
