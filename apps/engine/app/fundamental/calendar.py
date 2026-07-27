"""Calendrier économique et filtre d'annonces (fail-closed).

Un scalp XAUUSD qui trade pendant NFP/CPI/FOMC subit des spreads multipliés et
un slippage massif : la garde de spread existante est réactive, ce filtre est
préventif — aucun NOUVEL ordre dans les fenêtres configurées autour des
annonces qui touchent les devises suivies (USD par défaut pour l'or).

Principe fail-closed : si le filtre est activé mais que le calendrier est
indisponible ou trop ancien, on BLOQUE les nouveaux signaux au lieu de supposer
qu'il n'y a aucune annonce. Les clôtures de positions ne passent jamais par ce
filtre (réduire le risque reste toujours permis).

Le fournisseur est derrière une interface abstraite pour pouvoir en changer
(ForexFactory aujourd'hui, autre source demain) sans toucher au filtre.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from app.config import Settings

logger = logging.getLogger("nexagold.news")

# Flux hebdomadaire public ForexFactory (aucune clé requise).
_FOREX_FACTORY_URLS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
)

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"


@dataclass(frozen=True)
class CalendarEvent:
    time: datetime  # UTC, tz-aware
    currency: str  # "USD", "EUR"...
    impact: str  # HIGH / MEDIUM / LOW
    title: str

    def to_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "currency": self.currency,
            "impact": self.impact,
            "title": self.title,
        }


class EconomicCalendarProvider(ABC):
    """Source de calendrier économique interchangeable."""

    name: str = "abstract"

    @abstractmethod
    async def fetch_events(self) -> list[CalendarEvent]:
        """Événements de la période courante (semaine en cours et suivante).

        Doit lever une exception en cas d'échec — le filtre décide alors quoi
        faire (garder l'ancien cache, puis fail-closed passé l'âge maximal).
        """
        raise NotImplementedError


def _parse_impact(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    if value == "high":
        return HIGH
    if value == "medium":
        return MEDIUM
    if value == "low":
        return LOW
    # "Holiday", "Non-Economic"... : ignoré (pas une annonce datée à impact).
    return None


def parse_forex_factory(payload: list[dict]) -> list[CalendarEvent]:
    """Parsing défensif du flux ForexFactory (liste de dicts JSON)."""
    events: list[CalendarEvent] = []
    for row in payload or []:
        if not isinstance(row, dict):
            continue
        impact = _parse_impact(row.get("impact"))
        currency = str(row.get("country") or "").strip().upper()
        raw_date = row.get("date")
        if impact is None or not currency or not raw_date:
            continue
        try:
            when = datetime.fromisoformat(str(raw_date))
        except ValueError:
            continue
        if when.tzinfo is None:
            # Le flux fournit normalement un offset ; sans lui on suppose UTC
            # (hypothèse conservatrice documentée plutôt qu'un rejet muet).
            when = when.replace(tzinfo=timezone.utc)
        events.append(
            CalendarEvent(
                time=when.astimezone(timezone.utc),
                currency=currency,
                impact=impact,
                title=str(row.get("title") or "Annonce économique"),
            )
        )
    return events


class ForexFactoryProvider(EconomicCalendarProvider):
    name = "forexfactory"

    def __init__(self, timeout_seconds: float = 15.0):
        self._timeout = timeout_seconds

    async def fetch_events(self) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for url in _FOREX_FACTORY_URLS:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    events.extend(parse_forex_factory(response.json()))
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append(f"{url}: {exc}")
        if not events and errors:
            raise RuntimeError(
                "Calendrier économique indisponible: " + " | ".join(errors)
            )
        if errors:
            logger.warning("Calendrier partiel (%s)", " | ".join(errors))
        return events


class NewsFilter:
    """Verdict d'autorisation des NOUVEAUX ordres vis-à-vis des annonces."""

    def __init__(self, settings: Settings, provider: EconomicCalendarProvider):
        self._settings = settings
        self._provider = provider
        self._events: list[CalendarEvent] = []
        self._fetched_at: datetime | None = None
        self._last_error: str | None = None
        self._currencies = {
            c.strip().upper()
            for c in settings.news_currencies.split(",")
            if c.strip()
        }

    def _windows(self, impact: str) -> tuple[timedelta, timedelta] | None:
        s = self._settings
        if impact == HIGH:
            return (
                timedelta(minutes=s.news_block_high_pre_minutes),
                timedelta(minutes=s.news_block_high_post_minutes),
            )
        if impact == MEDIUM:
            return (
                timedelta(minutes=s.news_block_medium_pre_minutes),
                timedelta(minutes=s.news_block_medium_post_minutes),
            )
        return None  # LOW : jamais bloquant

    async def _maybe_refresh(self, now: datetime) -> None:
        fresh_until = timedelta(minutes=self._settings.news_refresh_minutes)
        if self._fetched_at is not None and now - self._fetched_at < fresh_until:
            return
        try:
            self._events = await self._provider.fetch_events()
            self._fetched_at = now
            self._last_error = None
            logger.info(
                "Calendrier économique rafraîchi (%d événements, source %s)",
                len(self._events),
                self._provider.name,
            )
        except Exception as exc:  # noqa: BLE001 — l'échec est un état géré (fail-closed)
            self._last_error = str(exc)
            logger.warning("Rafraîchissement du calendrier échoué: %s", exc)

    async def check(self, now: datetime | None = None) -> dict:
        """Renvoie {"blocked": bool, "reason": str, "event": dict | None}."""
        if not self._settings.news_filter_enabled:
            return {"blocked": False, "reason": "Filtre d'annonces désactivé", "event": None}

        now = now or datetime.now(timezone.utc)
        await self._maybe_refresh(now)

        max_age = timedelta(minutes=self._settings.news_max_age_minutes)
        if self._fetched_at is None:
            return {
                "blocked": True,
                "reason": (
                    "Calendrier économique jamais chargé "
                    f"({self._last_error or 'aucune donnée'}) — fail-closed"
                ),
                "event": None,
            }
        if now - self._fetched_at > max_age:
            return {
                "blocked": True,
                "reason": (
                    f"Calendrier économique trop ancien "
                    f"(>{self._settings.news_max_age_minutes} min) — fail-closed"
                ),
                "event": None,
            }

        for event in self._events:
            if event.currency not in self._currencies:
                continue
            windows = self._windows(event.impact)
            if windows is None:
                continue
            pre, post = windows
            if event.time - pre <= now <= event.time + post:
                return {
                    "blocked": True,
                    "reason": (
                        f"Annonce {event.impact} {event.currency} "
                        f"« {event.title} » à {event.time.strftime('%H:%M')} UTC "
                        f"(fenêtre -{int(pre.total_seconds() // 60)}/"
                        f"+{int(post.total_seconds() // 60)} min)"
                    ),
                    "event": event.to_dict(),
                }
        return {"blocked": False, "reason": "Aucune annonce bloquante", "event": None}

    def upcoming(self, now: datetime | None = None, hours: int = 24) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        horizon = now + timedelta(hours=hours)
        selected = [
            e
            for e in self._events
            if e.currency in self._currencies
            and e.impact in (HIGH, MEDIUM)
            and now - timedelta(hours=1) <= e.time <= horizon
        ]
        return [e.to_dict() for e in sorted(selected, key=lambda e: e.time)]

    def status(self) -> dict:
        return {
            "enabled": self._settings.news_filter_enabled,
            "provider": self._provider.name,
            "currencies": sorted(self._currencies),
            "events_cached": len(self._events),
            "fetched_at": self._fetched_at.isoformat() if self._fetched_at else None,
            "last_error": self._last_error,
            "windows_minutes": {
                "high": [
                    self._settings.news_block_high_pre_minutes,
                    self._settings.news_block_high_post_minutes,
                ],
                "medium": [
                    self._settings.news_block_medium_pre_minutes,
                    self._settings.news_block_medium_post_minutes,
                ],
            },
        }
