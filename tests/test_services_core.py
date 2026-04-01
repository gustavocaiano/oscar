from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from personal_assistant_bot.config import Settings
from personal_assistant_bot.services import AssistantService
from personal_assistant_bot.storage import SQLiteStorage


@dataclass
class FakeCalendarService:
    configured: bool = False
    events: list[object] | None = None

    def list_events(self, *, start, end):
        del start, end
        return list(self.events or [])

    def create_event(self, *, start, end, summary, description=None):
        return type("Event", (), {"summary": summary, "start": start, "end": end, "uid": "evt-1"})


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


def build_service(tmp_path: Path, calendar: FakeCalendarService | None = None) -> AssistantService:
    settings = build_settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    return AssistantService(storage=storage, calendar=calendar or FakeCalendarService(), settings=settings)


def test_task_and_shopping_lifecycle(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    task_ids = service.create_items(chat_id=1, user_id=2, kind="task", titles=["Buy milk", "Call bank"])
    shop_ids = service.create_items(chat_id=1, user_id=2, kind="shopping", titles=["Eggs"])

    assert len(task_ids) == 2
    assert len(shop_ids) == 1

    service.rename_item(chat_id=1, user_id=2, kind="task", item_id=task_ids[0], title="Buy oat milk")
    tasks = service.list_items(chat_id=1, user_id=2, kind="task")
    assert [task.title for task in tasks] == ["Buy oat milk", "Call bank"]

    service.complete_item(chat_id=1, user_id=2, kind="shopping", item_id=shop_ids[0])
    shopping = service.list_items(chat_id=1, user_id=2, kind="shopping")
    assert shopping == []


def test_notes_reminders_and_briefing(tmp_path: Path) -> None:
    calendar = FakeCalendarService(
        configured=True,
        events=[
            type(
                "Event",
                (),
                {
                    "summary": "Dentist",
                    "start": datetime(2026, 4, 1, 14, 0, tzinfo=timezone.utc),
                    "end": datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc),
                    "uid": "evt-1",
                },
            )
        ],
    )
    service = build_service(tmp_path, calendar=calendar)

    service.create_items(chat_id=10, user_id=11, kind="task", titles=["Renew passport"])
    service.create_items(chat_id=10, user_id=11, kind="shopping", titles=["Coffee"])
    service.add_note(chat_id=10, user_id=11, kind="note", content="Gift idea for Ana")
    reminder_id = service.create_reminder(chat_id=10, user_id=11, due_text="2026-04-01 09:00", message="Call the bank")

    reminders = service.list_reminders(chat_id=10, user_id=11, pending_only=True)
    assert reminders[0].id == reminder_id

    briefing = service.build_briefing(chat_id=10, user_id=11, label="Morning briefing")
    assert "Renew passport" in briefing
    assert "Coffee" in briefing
    assert "Gift idea for Ana" in briefing
    assert "Dentist" in briefing
