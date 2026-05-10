from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from personal_assistant_bot.bible_integration import BibleChapter, BibleVerse, next_bible_position
from personal_assistant_bot.config import Settings
from personal_assistant_bot.services import AssistantService
from personal_assistant_bot.storage import SQLiteStorage


@dataclass
class FakeCalendarService:
    configured: bool = False

    def list_events(self, *, start, end):
        del start, end
        return []

    def create_event(self, *, start, end, summary, description=None):
        del start, end, summary, description
        raise AssertionError("not used")


class FakeBibleClient:
    configured = True

    async def fetch_chapter(self, *, translation: str, book_abbrev: str, chapter: int) -> BibleChapter:
        return BibleChapter(
            book_abbrev=book_abbrev,
            book_name="Gênesis" if book_abbrev == "gn" else "Apocalipse",
            chapter=chapter,
            translation=translation,
            verses=[BibleVerse(number=1, text="Texto do versículo.")],
        )


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


def build_bible_service(tmp_path: Path) -> AssistantService:
    settings = replace(build_settings(tmp_path), bible_enabled=True, bible_daily_time="09:00")
    storage = SQLiteStorage(settings.database_path)
    return AssistantService(storage=storage, calendar=FakeCalendarService(), settings=settings, bible=FakeBibleClient())


def test_bible_progress_defaults_to_genesis_one(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "assistant.sqlite3")

    progress = storage.ensure_bible_progress(chat_id=1, user_id=2, translation="nvi")

    assert progress.next_book == "gn"
    assert progress.next_chapter == 1
    assert progress.chapters_read == 0


def test_bible_progress_advances_within_book_and_to_next_book(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "assistant.sqlite3")
    storage.ensure_bible_progress(chat_id=1, user_id=2, translation="nvi")

    next_book, next_chapter = next_bible_position("gn", 1) or (None, None)
    assert storage.advance_bible_progress(
        chat_id=1,
        current_book="gn",
        current_chapter=1,
        next_book=next_book,
        next_chapter=next_chapter,
    )
    progress = storage.get_bible_progress(chat_id=1)
    assert progress is not None
    assert (progress.next_book, progress.next_chapter, progress.chapters_read) == ("gn", 2, 1)

    storage.set_bible_progress(chat_id=1, user_id=2, translation="nvi", next_book="gn", next_chapter=50)
    next_book, next_chapter = next_bible_position("gn", 50) or (None, None)
    assert storage.advance_bible_progress(
        chat_id=1,
        current_book="gn",
        current_chapter=50,
        next_book=next_book,
        next_chapter=next_chapter,
    )
    progress = storage.get_bible_progress(chat_id=1)
    assert progress is not None
    assert (progress.next_book, progress.next_chapter) == ("ex", 1)


def test_bible_progress_completion_does_not_wrap(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "assistant.sqlite3")
    storage.set_bible_progress(chat_id=1, user_id=2, translation="nvi", next_book="ap", next_chapter=22)

    assert storage.advance_bible_progress(
        chat_id=1,
        current_book="ap",
        current_chapter=22,
        next_book=None,
        next_chapter=None,
    )
    progress = storage.get_bible_progress(chat_id=1)
    assert progress is not None
    assert progress.next_book is None
    assert progress.next_chapter is None
    assert progress.completed_at is not None


def test_daily_bible_prompt_claim_is_unique_per_date(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "assistant.sqlite3")

    assert storage.claim_daily_bible_prompt(chat_id=1, prompt_date="2026-04-01", stale_after_seconds=60)
    assert not storage.claim_daily_bible_prompt(chat_id=1, prompt_date="2026-04-01", stale_after_seconds=60)
    storage.mark_daily_bible_prompt_sent(chat_id=1, prompt_date="2026-04-01")
    assert not storage.claim_daily_bible_prompt(chat_id=1, prompt_date="2026-04-01", stale_after_seconds=60)


def test_daily_bible_prompt_claim_reclaims_stale_claim(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "assistant.sqlite3")

    assert storage.claim_daily_bible_prompt(chat_id=1, prompt_date="2026-04-01", stale_after_seconds=60)
    assert storage.claim_daily_bible_prompt(chat_id=1, prompt_date="2026-04-01", stale_after_seconds=0)


def test_scheduler_creates_one_bible_prompt_per_due_date(tmp_path: Path) -> None:
    service = build_bible_service(tmp_path)
    service.ensure_chat(chat_id=10, user_id=20)

    before = service.get_due_notifications(now_utc=datetime(2026, 4, 1, 8, 59, tzinfo=UTC))
    due = service.get_due_notifications(now_utc=datetime(2026, 4, 1, 9, 0, tzinfo=UTC))
    duplicate = service.get_due_notifications(now_utc=datetime(2026, 4, 1, 9, 1, tzinfo=UTC))

    assert not any(notification.notification_type == "bible_prompt" for notification in before)
    bible_prompts = [notification for notification in due if notification.notification_type == "bible_prompt"]
    assert len(bible_prompts) == 1
    assert bible_prompts[0].reply_markup_key == "bible_prompt"
    assert "Pronto" in bible_prompts[0].text
    assert not any(notification.notification_type == "bible_prompt" for notification in duplicate)


def test_scheduler_does_not_create_bible_catchup_prompts(tmp_path: Path) -> None:
    service = build_bible_service(tmp_path)
    service.ensure_chat(chat_id=10, user_id=20)

    notifications = service.get_due_notifications(now_utc=datetime(2026, 4, 6, 12, 0, tzinfo=UTC))

    bible_prompts = [notification for notification in notifications if notification.notification_type == "bible_prompt"]
    assert len(bible_prompts) == 1
    assert bible_prompts[0].claim_date == "2026-04-06"


def test_scheduler_suppresses_bible_prompt_after_completion(tmp_path: Path) -> None:
    service = build_bible_service(tmp_path)
    service.ensure_chat(chat_id=10, user_id=20)
    service.storage.set_bible_progress(
        chat_id=10,
        user_id=20,
        translation="nvi",
        next_book=None,
        next_chapter=None,
        completed_at="2026-04-01T00:00:00+00:00",
    )

    notifications = service.get_due_notifications(now_utc=datetime(2026, 4, 2, 9, 0, tzinfo=UTC))

    assert not any(notification.notification_type == "bible_prompt" for notification in notifications)
