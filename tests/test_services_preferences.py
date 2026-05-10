from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from personal_assistant_bot.config import Settings
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


def build_service(tmp_path: Path) -> AssistantService:
    settings = build_settings(tmp_path)
    storage = SQLiteStorage(settings.database_path)
    return AssistantService(storage=storage, calendar=FakeCalendarService(), settings=settings)


CHAT_ID = 1
USER_ID = 1


class TestRemoveNote:
    def test_returns_true_when_note_exists(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        note_id = svc.add_note(chat_id=CHAT_ID, user_id=USER_ID, kind="note", content="shopping list")
        assert svc.remove_note(chat_id=CHAT_ID, user_id=USER_ID, note_id=note_id) is True

    def test_returns_false_for_nonexistent_note_id(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        assert svc.remove_note(chat_id=CHAT_ID, user_id=USER_ID, note_id=9999) is False


class TestUpdatePreferenceToggle:
    @pytest.mark.parametrize("key", ["morning", "hours", "evening", "reminders"])
    def test_enable_returns_key_on(self, tmp_path: Path, key: str) -> None:
        svc = build_service(tmp_path)
        result = svc.update_preference_toggle(chat_id=CHAT_ID, user_id=USER_ID, key=key, enabled=True)
        assert result == f"{key} → on"

    @pytest.mark.parametrize("key", ["morning", "hours", "evening", "reminders"])
    def test_disable_returns_key_off(self, tmp_path: Path, key: str) -> None:
        svc = build_service(tmp_path)
        result = svc.update_preference_toggle(chat_id=CHAT_ID, user_id=USER_ID, key=key, enabled=False)
        assert result == f"{key} → off"

    def test_invalid_key_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Choose: morning, hours, evening, reminders"):
            svc.update_preference_toggle(chat_id=CHAT_ID, user_id=USER_ID, key="invalid", enabled=True)


class TestUpdatePreferenceTime:
    def test_valid_morning_time(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        result = svc.update_preference_time(chat_id=CHAT_ID, user_id=USER_ID, key="morning", time_value="07:00")
        assert result == "morning time → 07:00"

    def test_invalid_time_format_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Format: HH:MM"):
            svc.update_preference_time(chat_id=CHAT_ID, user_id=USER_ID, key="morning", time_value="25:00")

    def test_invalid_key_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Choose: morning, hours, evening"):
            svc.update_preference_time(chat_id=CHAT_ID, user_id=USER_ID, key="invalid", time_value="07:00")


class TestUpdateTimezone:
    def test_valid_timezone(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        result = svc.update_timezone(chat_id=CHAT_ID, user_id=USER_ID, timezone_name="Europe/Lisbon")
        assert result == "Timezone → Europe/Lisbon"

    def test_invalid_timezone_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Invalid timezone"):
            svc.update_timezone(chat_id=CHAT_ID, user_id=USER_ID, timezone_name="Invalid/Zone")


class TestGetPreferencesSummary:
    def test_contains_all_fields(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        svc.set_hourly_rate(chat_id=CHAT_ID, user_id=USER_ID, rate=50.0)
        summary = svc.get_preferences_summary(chat_id=CHAT_ID, user_id=USER_ID)
        assert "Timezone: UTC" in summary
        assert "Morning brief:" in summary
        assert "Hour reminder:" in summary
        assert "Evening wrap-up:" in summary
        assert "Reminder alerts:" in summary
        assert "Hourly rate: 50€/h" in summary


class TestSetHourlyRateNonPositive:
    def test_zero_rate_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Hourly rate must be positive"):
            svc.set_hourly_rate(chat_id=CHAT_ID, user_id=USER_ID, rate=0)

    def test_negative_rate_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Hourly rate must be positive"):
            svc.set_hourly_rate(chat_id=CHAT_ID, user_id=USER_ID, rate=-5)


class TestCreateItemsEmptyTitles:
    def test_empty_and_whitespace_titles_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Provide at least one item"):
            svc.create_items(chat_id=CHAT_ID, user_id=USER_ID, kind="task", titles=["  ", ""])


class TestAddNoteEmptyContent:
    def test_whitespace_content_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Note content required"):
            svc.add_note(chat_id=CHAT_ID, user_id=USER_ID, kind="note", content="  ")


class TestCreateReminderEmptyMessage:
    def test_whitespace_message_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Reminder text required"):
            svc.create_reminder(chat_id=CHAT_ID, user_id=USER_ID, due_text="2099-01-01 10:00", message="  ")


class TestRenameItemEmptyTitle:
    def test_whitespace_title_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        item_ids = svc.create_items(chat_id=CHAT_ID, user_id=USER_ID, kind="task", titles=["original"])
        with pytest.raises(AssistantError, match="Provide a new title"):
            svc.rename_item(chat_id=CHAT_ID, user_id=USER_ID, kind="task", item_id=item_ids[0], title="  ")


class TestListNotesWithQuery:
    def test_search_returns_only_matching_note(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        svc.add_note(chat_id=CHAT_ID, user_id=USER_ID, kind="note", content="python tip")
        svc.add_note(chat_id=CHAT_ID, user_id=USER_ID, kind="note", content="cooking recipe")
        results = svc.list_notes(chat_id=CHAT_ID, user_id=USER_ID, query="python")
        assert len(results) == 1
        assert results[0].content == "python tip"

    def test_no_results_returns_empty_list(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        svc.add_note(chat_id=CHAT_ID, user_id=USER_ID, kind="note", content="python tip")
        results = svc.list_notes(chat_id=CHAT_ID, user_id=USER_ID, query="nonexistent")
        assert results == []


class TestUpdateReminder:
    def test_update_existing_reminder_status(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        reminder_id = svc.create_reminder(
            chat_id=CHAT_ID, user_id=USER_ID, due_text="2099-06-01 09:00", message="test reminder"
        )
        svc.update_reminder(chat_id=CHAT_ID, user_id=USER_ID, reminder_id=reminder_id, status="done")
        reminders = svc.list_reminders(chat_id=CHAT_ID, user_id=USER_ID)
        updated = next(r for r in reminders if r.id == reminder_id)
        assert updated.status == "done"

    def test_update_nonexistent_reminder_raises(self, tmp_path: Path) -> None:
        svc = build_service(tmp_path)
        with pytest.raises(AssistantError, match="Reminder #9999 not found"):
            svc.update_reminder(chat_id=CHAT_ID, user_id=USER_ID, reminder_id=9999, status="done")
