from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from personal_assistant_bot.config import Settings
import pytest

from personal_assistant_bot.services import AssistantError, AssistantService
from personal_assistant_bot.storage import SQLiteStorage


@dataclass
class FakeCalendarService:
    configured: bool = False

    def list_events(self, *, start, end):
        del start, end
        return []

    def create_event(self, *, start, end, summary, description=None):
        del description
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
        morning_brief_time="00:00",
        hour_reminder_time="00:00",
        evening_wrap_up_time="00:00",
        reminder_scan_seconds=60,
        caldav_url=None,
        caldav_username=None,
        caldav_password=None,
        caldav_calendar_name=None,
        log_level=20,
    )


def build_service(tmp_path: Path) -> AssistantService:
    settings = build_settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    return AssistantService(storage=storage, calendar=FakeCalendarService(), settings=settings)


def test_confirm_approval_executes_same_tool_layer(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    pending = service.create_pending_approval(
        chat_id=1,
        user_id=2,
        action_type="create_task",
        payload={"title": "Buy apples"},
        prompt_text="Add task Buy apples",
    )

    result = service.confirm_approval(chat_id=1, user_id=2, token=pending.token)

    assert "Created task" in result
    tasks = service.list_items(chat_id=1, user_id=2, kind="task")
    assert [task.title for task in tasks] == ["Buy apples"]


def test_scheduler_generates_notifications_and_marks_state(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.ensure_chat(chat_id=10, user_id=20)
    service.create_items(chat_id=10, user_id=20, kind="task", titles=["Write report"])
    service.create_reminder(chat_id=10, user_id=20, due_text="2026-04-01 00:00", message="Call mom")

    notifications = service.get_due_notifications(now_utc=datetime(2026, 4, 1, 0, 1, tzinfo=timezone.utc))

    texts = [notification.text for notification in notifications]
    assert any("Reminder: Call mom" in text for text in texts)
    assert any("Morning briefing" in text for text in texts)
    assert any("log your hours" in text for text in texts)
    assert any("Evening wrap-up" in text for text in texts)

    for notification in notifications:
        service.mark_notification_delivered(notification)

    reminders = service.list_reminders(chat_id=10, user_id=20, pending_only=False)
    assert reminders[0].status == "sent"


def test_malformed_approval_payload_does_not_leave_token_stuck(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    pending = service.create_pending_approval(
        chat_id=1,
        user_id=2,
        action_type="create_task",
        payload={},
        prompt_text="Broken task action",
    )

    with pytest.raises(AssistantError):
        service.confirm_approval(chat_id=1, user_id=2, token=pending.token)

    approval = service.storage.get_approval(token=pending.token, user_id=2, chat_id=1)
    assert approval is not None
    assert approval.status == "pending"
