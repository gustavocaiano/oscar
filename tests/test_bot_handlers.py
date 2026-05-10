from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from personal_assistant_bot.bot import PersonalAssistantBot
from personal_assistant_bot.config import Settings
from personal_assistant_bot.services import AssistantService
from personal_assistant_bot.storage import SQLiteStorage

CHAT_ID = 1
USER_ID = 10


def build_settings(tmp_path: Path, allowed_chat_ids: frozenset[int] | None = None) -> Settings:
    return Settings(
        telegram_bot_token="token",
        allowed_chat_ids=allowed_chat_ids if allowed_chat_ids is not None else frozenset(),
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


@dataclass
class FakeCalendarService:
    configured: bool = False

    def list_events(self, *, start, end):
        del start, end
        return []

    def create_event(self, *, start, end, summary, description=None):
        del start, end, summary, description
        return None


@dataclass
class FakeUser:
    id: int


@dataclass
class FakeChat:
    id: int


class FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.replies: list[dict[str, object]] = []

    async def reply_text(self, text: str, reply_markup=None):
        self.replies.append({"text": text, "reply_markup": reply_markup})


@dataclass
class FakeUpdate:
    effective_message: FakeMessage | None
    effective_chat: FakeChat | None
    effective_user: FakeUser | None
    callback_query: None = None


class FakeContext:
    def __init__(self, args: list[str] | None = None):
        self.args = args or []


class FakeAIClient:
    configured = True

    async def respond(self, *, user_message, history, tool_snapshot, read_only_tool_executor=None):
        del user_message, history, tool_snapshot, read_only_tool_executor
        return None


class FakeTranscriber:
    def unavailable_message(self):
        return None

    async def transcribe_file(self, audio_path):
        del audio_path
        return None


def build_bot(tmp_path: Path, allowed_chat_ids: frozenset[int] | None = None) -> PersonalAssistantBot:
    settings = build_settings(tmp_path, allowed_chat_ids)
    storage = SQLiteStorage(settings.database_path)
    assistant = AssistantService(storage=storage, calendar=FakeCalendarService(), settings=settings)
    return PersonalAssistantBot(
        settings=settings, assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeTranscriber()
    )


def run(handler, update, context):
    return asyncio.run(handler(update, context))


# ---------------------------------------------------------------------------
# hours_handler
# ---------------------------------------------------------------------------


def test_hours_handler_no_args_shows_usage(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=[])

    run(bot.hours_handler, update, context)

    assert message.replies
    assert "/h add" in message.replies[0]["text"]


def test_hours_handler_add_2h30m(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["add", "2h", "30m"])

    run(bot.hours_handler, update, context)

    assert message.replies
    assert "2h 30m" in message.replies[0]["text"]


def test_hours_handler_month(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["month"])

    run(bot.hours_handler, update, context)

    assert message.replies
    assert "Month" in message.replies[0]["text"]


def test_hours_handler_euro(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["euro"])

    run(bot.hours_handler, update, context)

    assert message.replies
    assert "€" in message.replies[0]["text"]


def test_hours_handler_config_35(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["config", "35"])

    run(bot.hours_handler, update, context)

    assert message.replies
    assert "35€/h" in message.replies[0]["text"]


def test_hours_handler_config_zero_rejects(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["config", "0"])

    run(bot.hours_handler, update, context)

    assert message.replies
    assert "positive" in message.replies[0]["text"].lower()


def test_hours_handler_unknown_subcommand(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["unknown"])

    run(bot.hours_handler, update, context)

    assert message.replies
    assert "Unknown /h subcommand" in message.replies[0]["text"]


def test_hours_handler_add_invalid_format(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["add", "abc"])

    run(bot.hours_handler, update, context)

    assert message.replies
    assert "h/m format" in message.replies[0]["text"] or "decimal" in message.replies[0]["text"].lower()


# ---------------------------------------------------------------------------
# note_handler
# ---------------------------------------------------------------------------


def test_note_handler_no_args_shows_usage(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=[])

    run(bot.note_handler, update, context)

    assert message.replies
    assert "/note add" in message.replies[0]["text"]


def test_note_handler_add_saves_note(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["add", "Test", "note", "text"])

    run(bot.note_handler, update, context)

    assert message.replies
    reply_text = message.replies[0]["text"]
    assert "Note #" in reply_text
    assert "saved" in reply_text.lower()


def test_note_handler_inbox_saves_inbox(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["inbox", "Some", "thought"])

    run(bot.note_handler, update, context)

    assert message.replies
    reply_text = message.replies[0]["text"]
    assert "Inbox #" in reply_text
    assert "saved" in reply_text.lower()


def test_note_handler_list_replies(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["list"])

    run(bot.note_handler, update, context)

    assert message.replies


def test_note_handler_search_replies(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    # Add a note first so search has something to find
    add_msg = FakeMessage()
    add_update = FakeUpdate(
        effective_message=add_msg, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID)
    )
    run(bot.note_handler, add_update, FakeContext(args=["add", "Test", "note"]))

    search_msg = FakeMessage()
    search_update = FakeUpdate(
        effective_message=search_msg, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID)
    )
    context = FakeContext(args=["search", "Test"])

    run(bot.note_handler, search_update, context)

    assert search_msg.replies


def test_note_handler_delete_without_id(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["delete"])

    run(bot.note_handler, update, context)

    assert message.replies
    assert "note ID" in message.replies[0]["text"].lower() or "provide" in message.replies[0]["text"].lower()


def test_note_handler_delete_nonexistent(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["delete", "999"])

    run(bot.note_handler, update, context)

    assert message.replies
    assert "not found" in message.replies[0]["text"].lower()


def test_note_handler_unknown_subcommand(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["unknown"])

    run(bot.note_handler, update, context)

    assert message.replies
    assert "Unknown /note subcommand" in message.replies[0]["text"]


# ---------------------------------------------------------------------------
# preference_handler
# ---------------------------------------------------------------------------


def test_preference_handler_no_args_shows_usage(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=[])

    run(bot.preference_handler, update, context)

    assert message.replies
    assert "/pref" in message.replies[0]["text"]


def test_preference_handler_show_contains_timezone(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["show"])

    run(bot.preference_handler, update, context)

    assert message.replies
    assert "Timezone" in message.replies[0]["text"]


def test_preference_handler_enable_morning(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["enable", "morning"])

    run(bot.preference_handler, update, context)

    assert message.replies
    assert "morning" in message.replies[0]["text"]
    assert "on" in message.replies[0]["text"]


def test_preference_handler_disable_hours(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["disable", "hours"])

    run(bot.preference_handler, update, context)

    assert message.replies
    assert "hours" in message.replies[0]["text"]
    assert "off" in message.replies[0]["text"]


def test_preference_handler_time_morning(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["time", "morning", "07:00"])

    run(bot.preference_handler, update, context)

    assert message.replies
    assert "morning" in message.replies[0]["text"]
    assert "07:00" in message.replies[0]["text"]


def test_preference_handler_timezone(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["timezone", "Europe/Lisbon"])

    run(bot.preference_handler, update, context)

    assert message.replies
    assert "Europe/Lisbon" in message.replies[0]["text"]


def test_preference_handler_enable_invalid_key(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["enable", "invalid"])

    run(bot.preference_handler, update, context)

    assert message.replies
    reply_text = message.replies[0]["text"]
    assert "morning" in reply_text and "hours" in reply_text


def test_preference_handler_time_invalid_key(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["time", "invalid", "07:00"])

    run(bot.preference_handler, update, context)

    assert message.replies
    reply_text = message.replies[0]["text"]
    assert "morning" in reply_text and "hours" in reply_text and "evening" in reply_text


def test_preference_handler_unknown_subcommand(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["unknown"])

    run(bot.preference_handler, update, context)

    assert message.replies
    assert "Unknown /pref subcommand" in message.replies[0]["text"]


# ---------------------------------------------------------------------------
# start_handler & help_handler
# ---------------------------------------------------------------------------


def test_start_handler_replies_non_empty(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext()

    run(bot.start_handler, update, context)

    assert message.replies
    assert message.replies[0]["text"].strip()


def test_help_handler_replies_non_empty(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext()

    run(bot.help_handler, update, context)

    assert message.replies
    assert message.replies[0]["text"].strip()


# ---------------------------------------------------------------------------
# cancel_handler
# ---------------------------------------------------------------------------


def test_cancel_handler_no_active_draft(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext()

    run(bot.cancel_handler, update, context)

    assert message.replies
    assert "No active flow to cancel." in message.replies[0]["text"]


def test_cancel_handler_with_active_draft(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    bot._drafts[(CHAT_ID, USER_ID)] = type("Draft", (), {"flow_type": "reminder_create"})()

    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext()

    run(bot.cancel_handler, update, context)

    assert message.replies
    assert "cancelled" in message.replies[0]["text"].lower()


# ---------------------------------------------------------------------------
# confirm_handler
# ---------------------------------------------------------------------------


def test_confirm_handler_no_token(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=[])

    run(bot.confirm_handler, update, context)

    assert message.replies
    assert "Usage: /confirm <token>" in message.replies[0]["text"]


def test_confirm_handler_with_valid_approval(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    approval = bot.assistant.create_pending_approval(
        chat_id=CHAT_ID,
        user_id=USER_ID,
        action_type="create_task",
        payload={"title": "test"},
        prompt_text="test",
    )

    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=[approval.token])

    run(bot.confirm_handler, update, context)

    assert message.replies
    assert message.replies[0]["text"]


def test_confirm_handler_nonexistent_token(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["deadbeef"])

    run(bot.confirm_handler, update, context)

    assert message.replies
    assert "not found" in message.replies[0]["text"].lower() or "Token" in message.replies[0]["text"]


# ---------------------------------------------------------------------------
# reject_handler
# ---------------------------------------------------------------------------


def test_reject_handler_no_token(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=[])

    run(bot.reject_handler, update, context)

    assert message.replies
    assert "Usage: /reject <token>" in message.replies[0]["text"]


def test_reject_handler_with_valid_approval(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    approval = bot.assistant.create_pending_approval(
        chat_id=CHAT_ID,
        user_id=USER_ID,
        action_type="create_task",
        payload={"title": "test"},
        prompt_text="test",
    )

    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=[approval.token])

    run(bot.reject_handler, update, context)

    assert message.replies
    assert message.replies[0]["text"]


def test_reject_handler_nonexistent_token(tmp_path: Path) -> None:
    bot = build_bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["deadbeef"])

    run(bot.reject_handler, update, context)

    assert message.replies
    assert "not found" in message.replies[0]["text"].lower() or "Token" in message.replies[0]["text"]


# ---------------------------------------------------------------------------
# _ensure_access with denied chat
# ---------------------------------------------------------------------------


def test_ensure_access_denied_chat_replies_not_enabled(tmp_path: Path) -> None:
    bot = build_bot(tmp_path, allowed_chat_ids=frozenset({999}))
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(CHAT_ID), effective_user=FakeUser(USER_ID))
    context = FakeContext(args=["month"])

    run(bot.hours_handler, update, context)

    # _ensure_access sends "Bot not enabled for this chat." when allowed_chat_ids is set
    # and the chat is not in the allow-list. The handler then returns early.
    assert message.replies
    assert "Bot not enabled for this chat" in message.replies[0]["text"]
