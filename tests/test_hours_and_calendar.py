from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from personal_assistant_bot.config import Settings
from personal_assistant_bot.hours import format_hours_total, format_subtotals, parse_getmm, parse_hours
from personal_assistant_bot.calendar_integration import CalendarService, normalize_caldav_datetime
from personal_assistant_bot.services import AssistantError, AssistantService
from personal_assistant_bot.storage import SQLiteStorage


@dataclass
class FakeCalendarService:
    configured: bool = False

    def list_events(self, *, start, end):
        del start, end
        return [
            type("Event", (), {"summary": "Doctor", "start": datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc), "end": datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc), "uid": "evt-1"})
        ]

    def create_event(self, *, start, end, summary, description=None):
        del description
        return type("Event", (), {"summary": summary, "start": start, "end": end, "uid": "evt-2"})


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        telegram_bot_token="token",
        allowed_chat_ids=frozenset(),
        database_path=tmp_path / "assistant.sqlite3",
        backend_base_url=None,
        backend_api_key=None,
        backend_model=None,
        backend_timeout_seconds=60.0,
        chat_history_limit=12,
        approval_ttl_minutes=30,
        default_timezone="UTC",
        morning_brief_time="08:00",
        hour_reminder_time="18:00",
        evening_wrap_up_time="20:00",
        reminder_scan_seconds=60,
        caldav_url=None,
        caldav_username=None,
        caldav_password=None,
        caldav_calendar_name=None,
        log_level=20,
    )


def build_service(tmp_path: Path, calendar) -> AssistantService:
    settings = build_settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    return AssistantService(storage=storage, calendar=calendar, settings=settings)


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("0", Decimal("0")),
        ("2h 30m", Decimal("2.5")),
        ("30m", Decimal("0.5")),
        ("-2h 30m", Decimal("-2.5")),
    ],
)
def test_parse_hours_preserves_hcounter_behavior(raw_text: str, expected: Decimal) -> None:
    assert parse_hours(raw_text) == expected


def test_parse_getmm_and_formatters_preserve_hcounter_behavior() -> None:
    assert parse_getmm("get04") == 4
    assert format_hours_total(Decimal("2.5")) == "2h 30m"
    assert format_subtotals(Decimal("1.5"), Decimal("3.5")) == "Day subtotal: 1h 30m\nMonth subtotal: 3h 30m"


def test_month_aggregation_uses_local_storage(tmp_path: Path) -> None:
    service = build_service(tmp_path, FakeCalendarService())
    service.add_hours(chat_id=10, user_id=20, raw_text="1.5")
    service.add_hours(chat_id=10, user_id=20, raw_text="2")
    assert "Month" in service.get_month_hours(chat_id=10, user_id=20)


def test_calendar_edge_cases(tmp_path: Path) -> None:
    service_without_calendar = build_service(tmp_path / "a", FakeCalendarService(configured=False))
    with pytest.raises(AssistantError):
        service_without_calendar.list_calendar_events(chat_id=1, user_id=2)

    service_with_calendar = build_service(tmp_path / "b", FakeCalendarService(configured=True))
    events = service_with_calendar.list_calendar_events(chat_id=1, user_id=2)
    assert events[0].summary == "Doctor"

    with pytest.raises(AssistantError):
        service_with_calendar.create_calendar_event(
            chat_id=1,
            user_id=2,
            start_text="2026-04-01 15:00",
            end_text="2026-04-01 14:00",
            summary="Broken event",
        )


def test_caldav_datetime_normalization_handles_all_day_values() -> None:
    normalized_date, is_all_day, original_date = normalize_caldav_datetime(
        datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc)
    )
    assert normalized_date.hour == 14
    assert is_all_day is False
    assert original_date is None

    all_day_date, all_day_flag, original_date = normalize_caldav_datetime(
        datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc).date()
    )
    assert all_day_date.hour == 0
    assert all_day_flag is True
    assert original_date.isoformat() == "2026-04-02"


def test_create_event_uses_icalendar_component_and_closes_client() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeDateField:
        def __init__(self, dt: datetime) -> None:
            self.dt = dt

    class FakeCreatedResource:
        __slots__ = ("icalendar_component",)

        def __init__(self, component: dict[str, object]) -> None:
            self.icalendar_component = component

    class FakeCalendar:
        def __init__(self, component: dict[str, object]) -> None:
            self._component = component

        def save_event(self, *, dtstart, dtend, summary, description):
            del dtstart, dtend, summary, description
            return FakeCreatedResource(self._component)

    start = datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)
    component = {
        "summary": "From icalendar_component",
        "dtstart": FakeDateField(start),
        "dtend": FakeDateField(end),
        "uid": "evt-ical-1",
    }

    service = CalendarService(url="https://example.test", username="user", password="pass", calendar_name=None)
    fake_client = FakeClient()
    fake_calendar = FakeCalendar(component)
    service._get_calendar = lambda: (fake_client, fake_calendar)  # type: ignore[method-assign]

    created_event = service.create_event(start=start, end=end, summary="ignored", description="ignored")

    assert created_event.summary == "From icalendar_component"
    assert created_event.start == start
    assert created_event.end == end
    assert created_event.uid == "evt-ical-1"
    assert fake_client.closed is True


def test_get_calendar_matches_display_name_case_insensitively(monkeypatch) -> None:
    class FakeCalendar:
        def get_display_name(self) -> str:
            return "Work"

    class FakePrincipal:
        def calendar(self, *, name: str):
            raise LookupError(name)

        def get_calendars(self):
            return [FakeCalendar()]

    class FakeClient:
        def __init__(self, *, url: str, username: str, password: str) -> None:
            del url, username, password

        def principal(self):
            return FakePrincipal()

        def close(self) -> None:
            return None

    monkeypatch.setattr("personal_assistant_bot.calendar_integration.DAVClient", FakeClient)

    service = CalendarService(
        url="https://example.test",
        username="user",
        password="pass",
        calendar_name=" work ",
    )

    _, calendar = service._get_calendar()

    assert calendar.get_display_name() == "Work"
