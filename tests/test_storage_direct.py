from __future__ import annotations

from pathlib import Path

import pytest

from personal_assistant_bot.config import Settings
from personal_assistant_bot.storage import SQLiteStorage


def build_storage(tmp_path: Path) -> SQLiteStorage:
    settings = Settings(
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
    return SQLiteStorage(settings.database_path)


def _ensure_prefs(storage: SQLiteStorage, chat_id: int = 1, user_id: int = 10) -> None:
    storage.ensure_chat_preferences(
        chat_id=chat_id,
        user_id=user_id,
        timezone_name="UTC",
        morning_brief_time="08:00",
        hour_reminder_time="18:00",
        evening_wrap_up_time="20:00",
    )


# ── 1. delete_note ──────────────────────────────────────────────────────────


def test_delete_note_returns_true_when_exists(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    note_id = storage.create_note(user_id=1, chat_id=10, kind="note", content="test")
    assert storage.delete_note(note_id=note_id, user_id=1, chat_id=10) is True


def test_delete_note_returns_false_when_already_deleted(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    note_id = storage.create_note(user_id=1, chat_id=10, kind="note", content="test")
    storage.delete_note(note_id=note_id, user_id=1, chat_id=10)
    assert storage.delete_note(note_id=note_id, user_id=1, chat_id=10) is False


def test_delete_note_returns_false_for_nonexistent_id(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    assert storage.delete_note(note_id=9999, user_id=1, chat_id=10) is False


# ── 2. update_reminder_status ───────────────────────────────────────────────


def test_update_reminder_status_returns_true_when_exists(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    rid = storage.create_reminder(user_id=1, chat_id=10, message="test", due_at="2026-01-01T09:00:00+00:00")
    assert storage.update_reminder_status(user_id=1, chat_id=10, reminder_id=rid, status="done") is True


def test_update_reminder_status_returns_false_for_nonexistent(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    assert storage.update_reminder_status(user_id=1, chat_id=10, reminder_id=9999, status="done") is False


# ── 3. get_chat_preferences LookupError ─────────────────────────────────────


def test_get_chat_preferences_raises_lookup_error_for_missing(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    with pytest.raises(LookupError, match="Chat preferences not found"):
        storage.get_chat_preferences(chat_id=9999)


# ── 4. update_chat_preferences with unknown field ───────────────────────────


def test_update_chat_preferences_raises_on_unknown_field(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    _ensure_prefs(storage, chat_id=1, user_id=10)
    with pytest.raises(ValueError, match="Unsupported preference fields"):
        storage.update_chat_preferences(1, unknown_field="value")


# ── 5. compare_and_set_chat_preference ──────────────────────────────────────


def test_compare_and_set_from_null(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    _ensure_prefs(storage, chat_id=1, user_id=10)
    assert (
        storage.compare_and_set_chat_preference(
            chat_id=1, field="last_morning_brief_on", expected=None, new_value="2026-01-01"
        )
        is True
    )


def test_compare_and_set_with_matching_expected(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    _ensure_prefs(storage, chat_id=1, user_id=10)
    storage.compare_and_set_chat_preference(
        chat_id=1, field="last_morning_brief_on", expected=None, new_value="2026-01-01"
    )
    assert (
        storage.compare_and_set_chat_preference(
            chat_id=1, field="last_morning_brief_on", expected="2026-01-01", new_value="2026-01-02"
        )
        is True
    )


def test_compare_and_set_with_mismatched_expected(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    _ensure_prefs(storage, chat_id=1, user_id=10)
    storage.compare_and_set_chat_preference(
        chat_id=1, field="last_morning_brief_on", expected=None, new_value="2026-01-01"
    )
    storage.compare_and_set_chat_preference(
        chat_id=1, field="last_morning_brief_on", expected="2026-01-01", new_value="2026-01-02"
    )
    assert (
        storage.compare_and_set_chat_preference(
            chat_id=1, field="last_morning_brief_on", expected="2026-01-01", new_value="2026-01-03"
        )
        is False
    )


def test_compare_and_set_raises_on_invalid_field(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    _ensure_prefs(storage, chat_id=1, user_id=10)
    with pytest.raises(ValueError, match="Unsupported compare-and-set field"):
        storage.compare_and_set_chat_preference(chat_id=1, field="invalid_field", expected=None, new_value="x")


# ── 6. aggregate_month_hours with invalid month ─────────────────────────────


def test_aggregate_month_hours_raises_on_month_zero(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    with pytest.raises(ValueError):
        storage.aggregate_month_hours(user_id=1, chat_id=10, year=2026, month=0)


def test_aggregate_month_hours_raises_on_month_thirteen(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    with pytest.raises(ValueError):
        storage.aggregate_month_hours(user_id=1, chat_id=10, year=2026, month=13)


# ── 7. get_list_item ────────────────────────────────────────────────────────


def test_get_list_item_returns_item(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    item_id = storage.create_list_item(user_id=1, chat_id=10, kind="task", title="Test")
    item = storage.get_list_item(user_id=1, chat_id=10, kind="task", item_id=item_id)
    assert item is not None
    assert item.title == "Test"
    assert item.kind == "task"
    assert item.id == item_id


def test_get_list_item_returns_none_for_nonexistent(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    assert storage.get_list_item(user_id=1, chat_id=10, kind="task", item_id=9999) is None


# ── 8. upsert_task_sync_link / get_task_sync_link ───────────────────────────


def test_upsert_and_get_task_sync_link(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    storage.upsert_task_sync_link(
        list_item_id=1, provider="kbplus", external_task_id="ext-1", external_board_id="board-1"
    )
    link = storage.get_task_sync_link(list_item_id=1, provider="kbplus")
    assert link is not None
    assert link.external_task_id == "ext-1"
    assert link.external_board_id == "board-1"


def test_get_task_sync_link_returns_none_for_other_provider(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    storage.upsert_task_sync_link(
        list_item_id=1, provider="kbplus", external_task_id="ext-1", external_board_id="board-1"
    )
    assert storage.get_task_sync_link(list_item_id=1, provider="other") is None


def test_upsert_task_sync_link_updates_existing(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    storage.upsert_task_sync_link(
        list_item_id=1, provider="kbplus", external_task_id="ext-1", external_board_id="board-1"
    )
    storage.upsert_task_sync_link(
        list_item_id=1, provider="kbplus", external_task_id="ext-2", external_board_id="board-2"
    )
    link = storage.get_task_sync_link(list_item_id=1, provider="kbplus")
    assert link is not None
    assert link.external_task_id == "ext-2"
    assert link.external_board_id == "board-2"


# ── 9. list_due_reminders ──────────────────────────────────────────────────


def test_list_due_reminders_includes_past_due(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    storage.create_reminder(user_id=1, chat_id=10, message="past reminder", due_at="2025-06-01T09:00:00+00:00")
    due = storage.list_due_reminders(due_before="2026-12-31T23:59:59+00:00")
    assert any(r.message == "past reminder" for r in due)


def test_list_due_reminders_excludes_future_due(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    storage.create_reminder(user_id=1, chat_id=10, message="future reminder", due_at="2099-06-01T09:00:00+00:00")
    due = storage.list_due_reminders(due_before="2026-12-31T23:59:59+00:00")
    assert not any(r.message == "future reminder" for r in due)


# ── 10. release_scheduled_notification_claim ─────────────────────────────────


def test_release_scheduled_notification_claim_allows_reclaim(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    _ensure_prefs(storage, chat_id=1, user_id=10)

    # First claim succeeds
    assert (
        storage.claim_scheduled_notification(
            chat_id=1, notification_type="morning_brief", claim_date="2026-01-01", stale_after_seconds=300
        )
        is True
    )

    # Release the claim
    storage.release_scheduled_notification_claim(chat_id=1, notification_type="morning_brief", claim_date="2026-01-01")

    # Claim again after release succeeds
    assert (
        storage.claim_scheduled_notification(
            chat_id=1, notification_type="morning_brief", claim_date="2026-01-01", stale_after_seconds=300
        )
        is True
    )
