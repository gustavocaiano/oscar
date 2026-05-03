from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

try:  # pragma: no cover - exercised indirectly depending on environment
    from caldav import DAVClient
except ImportError:  # pragma: no cover - allows unit tests without installed deps
    DAVClient = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class CalendarIntegrationError(RuntimeError):
    """Raised when calendar operations fail."""


@dataclass(frozen=True)
class CalendarEvent:
    summary: str
    start: datetime
    end: datetime
    uid: str | None
    all_day: bool = False
    start_date: date | None = None
    end_date: date | None = None


def normalize_caldav_datetime(value: date | datetime) -> tuple[datetime, bool, date | None]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value, False, None
        return value, False, None
    return datetime.combine(value, time.min, tzinfo=UTC), True, value


class CalendarService:
    def __init__(
        self,
        *,
        url: str | None,
        username: str | None,
        password: str | None,
        calendar_name: str | None,
    ):
        self.url = url
        self.username = username
        self.password = password
        self.calendar_name = calendar_name

    @property
    def configured(self) -> bool:
        return bool(self.url and self.username and self.password)

    def _calendar_display_name(self, calendar: Any) -> str | None:
        if hasattr(calendar, "get_display_name"):
            try:
                display_name = calendar.get_display_name()
            except Exception:  # pragma: no cover - depends on remote CalDAV server behavior
                display_name = None
            if display_name:
                return str(display_name).strip()
        raw_name = getattr(calendar, "name", None)
        if raw_name:
            return str(raw_name).strip()
        return None

    def _normalize_calendar_name(self, value: str) -> str:
        return " ".join(value.strip().casefold().split())

    def _get_calendar(self):
        if not self.configured:
            raise CalendarIntegrationError("Calendar integration is not configured")
        if DAVClient is None:
            raise CalendarIntegrationError("The 'caldav' package is not installed")
        client = DAVClient(url=self.url, username=self.username, password=self.password)
        try:
            principal = client.principal()
            calendars = principal.get_calendars() if hasattr(principal, "get_calendars") else principal.calendars()
            if not calendars:
                raise CalendarIntegrationError("No calendars were found for the configured CalDAV account")
            if self.calendar_name:
                target_name = self._normalize_calendar_name(self.calendar_name)
                try:
                    direct_calendar = principal.calendar(name=self.calendar_name.strip())
                    direct_name = self._calendar_display_name(direct_calendar) or self.calendar_name.strip()
                    logger.info("Resolved CalDAV calendar via direct lookup: %s", direct_name)
                    return client, direct_calendar
                except Exception as exc:  # pragma: no cover - depends on remote CalDAV server behavior
                    logger.warning("Direct CalDAV calendar lookup failed for '%s': %s", self.calendar_name, exc)
                for calendar in calendars:
                    display_name = self._calendar_display_name(calendar)
                    if display_name and self._normalize_calendar_name(display_name) == target_name:
                        logger.info("Resolved CalDAV calendar via display name: %s", display_name)
                        return client, calendar
                raise CalendarIntegrationError(
                    f"Calendar '{self.calendar_name}' was not found in the configured CalDAV account"
                )
            default_name = self._calendar_display_name(calendars[0]) or "first available calendar"
            logger.info("Using default CalDAV calendar: %s", default_name)
            return client, calendars[0]
        except Exception:
            client.close()
            raise

    def list_events(self, *, start: datetime, end: datetime) -> list[CalendarEvent]:
        client, calendar = self._get_calendar()
        try:
            events = calendar.search(start=start, end=end, event=True, expand=True)
            normalized: list[CalendarEvent] = []
            for event in events:
                component: Any = getattr(event, "icalendar_component", None)
                if component is None:
                    component = getattr(event, "component", None)
                if component is None:
                    continue
                dtstart = component.get("dtstart")
                dtend = component.get("dtend")
                if dtstart is None or dtend is None:
                    continue
                start_value, start_all_day, start_date = normalize_caldav_datetime(dtstart.dt)
                end_value, end_all_day, end_date = normalize_caldav_datetime(dtend.dt)
                normalized.append(
                    CalendarEvent(
                        summary=str(component.get("summary", "Untitled event")),
                        start=start_value,
                        end=end_value,
                        uid=str(component.get("uid")) if component.get("uid") else None,
                        all_day=start_all_day or end_all_day,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )
            normalized.sort(
                key=lambda item: item.start if item.start.tzinfo is not None else item.start.replace(tzinfo=UTC)
            )
            return normalized
        except Exception as exc:  # pragma: no cover - exercised via injected fakes in tests
            raise CalendarIntegrationError(f"Unable to read calendar events: {exc}") from exc
        finally:
            client.close()

    def create_event(
        self,
        *,
        start: datetime,
        end: datetime,
        summary: str,
        description: str | None = None,
    ) -> CalendarEvent:
        client, calendar = self._get_calendar()
        try:
            created = calendar.save_event(
                dtstart=start,
                dtend=end,
                summary=summary,
                description=description or "",
            )
            component: Any = getattr(created, "icalendar_component", None)
            if component is None:
                component = getattr(created, "component", None)
            if component is None:
                raise AttributeError("Created calendar event resource does not expose an iCalendar component")
            start_value, start_all_day, start_date = normalize_caldav_datetime(component.get("dtstart").dt)
            end_value, end_all_day, end_date = normalize_caldav_datetime(component.get("dtend").dt)
            return CalendarEvent(
                summary=str(component.get("summary", summary)),
                start=start_value,
                end=end_value,
                uid=str(component.get("uid")) if component.get("uid") else None,
                all_day=start_all_day or end_all_day,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:  # pragma: no cover - exercised via injected fakes in tests
            raise CalendarIntegrationError(f"Unable to create calendar event: {exc}") from exc
        finally:
            client.close()
