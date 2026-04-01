from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from personal_assistant_bot.ai import AIResponse
from personal_assistant_bot.bot import PersonalAssistantBot
from personal_assistant_bot.config import Settings
from personal_assistant_bot.services import PendingApproval


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


class FakeCallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.message = object()
        self.answers: list[dict[str, object]] = []
        self.edits: list[str] = []

    async def answer(self, text: str | None = None, show_alert: bool = False):
        self.answers.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text: str):
        self.edits.append(text)


@dataclass
class FakeUpdate:
    effective_message: FakeMessage | None
    effective_chat: FakeChat | None
    effective_user: FakeUser | None
    callback_query: FakeCallbackQuery | None = None


class FakeBot:
    def __init__(self):
        self.chat_actions: list[tuple[int, str]] = []

    async def send_chat_action(self, chat_id: int, action: str):
        self.chat_actions.append((chat_id, action))


@dataclass
class FakeContext:
    bot: FakeBot


class FakeAssistant:
    def __init__(self):
        self.chat_history: list[tuple[int, int, str, str]] = []
        self.confirm_calls: list[tuple[int, int, str]] = []
        self.reject_calls: list[tuple[int, int, str]] = []

    def ensure_chat(self, *, chat_id: int, user_id: int):
        return None

    def add_chat_history(self, *, chat_id: int, user_id: int, role: str, content: str) -> None:
        self.chat_history.append((chat_id, user_id, role, content))

    def get_chat_history(self, *, chat_id: int, user_id: int):
        return []

    def get_tool_snapshot(self, *, chat_id: int, user_id: int):
        return {"tasks": [], "shopping": []}

    def create_pending_approval(self, *, chat_id: int, user_id: int, action_type: str, payload: dict, prompt_text: str):
        return PendingApproval(token="abc123", prompt_text=prompt_text, expires_at="2026-04-01T12:00:00+00:00")

    def confirm_approval(self, *, chat_id: int, user_id: int, token: str) -> str:
        self.confirm_calls.append((chat_id, user_id, token))
        return "Created task #1"

    def reject_approval(self, *, chat_id: int, user_id: int, token: str) -> str:
        self.reject_calls.append((chat_id, user_id, token))
        return "Rejected pending action abc123"


class FakeAIClient:
    configured = True

    async def respond(self, *, user_message: str, history, tool_snapshot):
        del history, tool_snapshot
        return AIResponse(
            reply=f"I can do that for: {user_message}",
            proposed_action={
                "action_type": "create_task",
                "payload": {"title": "Buy apples"},
                "label": "Add task Buy apples",
            },
        )


def test_chat_handler_sends_inline_approval_buttons(tmp_path: Path) -> None:
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path),
        assistant=FakeAssistant(),
        ai_client=FakeAIClient(),
    )
    message = FakeMessage(text="add buy apples to my tasks")
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))
    context = FakeContext(bot=FakeBot())

    asyncio.run(bot.chat_handler(update, context))

    assert len(message.replies) == 1
    reply = message.replies[0]
    assert "Proposed action: Add task Buy apples" in reply["text"]
    markup = reply["reply_markup"]
    assert markup is not None
    first_row = markup.inline_keyboard[0]
    assert first_row[0].callback_data == "approve:abc123"
    assert first_row[1].callback_data == "reject:abc123"


def test_approval_callback_handler_confirms_action(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient())
    query = FakeCallbackQuery(data="approve:abc123")
    update = FakeUpdate(
        effective_message=None,
        effective_chat=FakeChat(10),
        effective_user=FakeUser(20),
        callback_query=query,
    )

    asyncio.run(bot.approval_callback_handler(update, FakeContext(bot=FakeBot())))

    assert assistant.confirm_calls == [(10, 20, "abc123")]
    assert query.answers[0]["text"] == "Action processed."
    assert query.edits == ["✅ Approved — Created task #1"]


def test_approval_callback_handler_rejects_action(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient())
    query = FakeCallbackQuery(data="reject:abc123")
    update = FakeUpdate(
        effective_message=None,
        effective_chat=FakeChat(10),
        effective_user=FakeUser(20),
        callback_query=query,
    )

    asyncio.run(bot.approval_callback_handler(update, FakeContext(bot=FakeBot())))

    assert assistant.reject_calls == [(10, 20, "abc123")]
    assert query.answers[0]["text"] == "Action processed."
    assert query.edits == ["❌ Rejected — Rejected pending action abc123"]


def test_parse_approval_callback_data_rejects_invalid_input(tmp_path: Path) -> None:
    bot = PersonalAssistantBot(settings=build_settings(tmp_path), assistant=FakeAssistant(), ai_client=FakeAIClient())

    assert bot._parse_approval_callback_data("approve:abc123") == ("approve", "abc123")
    assert bot._parse_approval_callback_data("reject:abc123") == ("reject", "abc123")
    assert bot._parse_approval_callback_data("approve:not valid") is None
    assert bot._parse_approval_callback_data("random") is None


def test_approval_callback_handler_respects_allowed_chat_ids(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "allowed_chat_ids": frozenset({999})})
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(settings=settings, assistant=assistant, ai_client=FakeAIClient())
    query = FakeCallbackQuery(data="approve:abc123")
    update = FakeUpdate(
        effective_message=None,
        effective_chat=FakeChat(10),
        effective_user=FakeUser(20),
        callback_query=query,
    )

    asyncio.run(bot.approval_callback_handler(update, FakeContext(bot=FakeBot())))

    assert assistant.confirm_calls == []
    assert query.answers[0]["text"] == "This bot is not enabled for this chat."
    assert query.answers[0]["show_alert"] is True
