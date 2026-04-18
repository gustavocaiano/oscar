from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from personal_assistant_bot.ai import AIResponse
from personal_assistant_bot.bot import PersonalAssistantBot
from personal_assistant_bot.config import Settings
from personal_assistant_bot.kbplus_integration import KbplusColumn, KbplusTask
from personal_assistant_bot.services import AssistantError, PendingApproval
from personal_assistant_bot.speech import TranscriptionResult


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
    args: list[str] | None = None

    def __post_init__(self) -> None:
        if self.args is None:
            self.args = []


@dataclass
class FakePreferences:
    timezone: str = "UTC"


class FakeAssistant:
    def __init__(self):
        self.chat_history: list[tuple[int, int, str, str]] = []
        self.confirm_calls: list[tuple[int, int, str]] = []
        self.reject_calls: list[tuple[int, int, str]] = []
        self.pending_calls: list[dict[str, object]] = []
        self.between_calls: list[tuple[datetime, datetime]] = []
        self.completed_calls: list[tuple[int, int, str, str | int]] = []
        self.renamed_calls: list[tuple[int, int, str, str | int, str]] = []
        self.kbplus = type("Kbplus", (), {"configured": True})()

    def ensure_chat(self, *, chat_id: int, user_id: int):
        del chat_id, user_id
        return FakePreferences()

    def add_chat_history(self, *, chat_id: int, user_id: int, role: str, content: str) -> None:
        self.chat_history.append((chat_id, user_id, role, content))

    def get_chat_history(self, *, chat_id: int, user_id: int):
        return []

    def get_tool_snapshot(self, *, chat_id: int, user_id: int):
        return {"tasks": [], "shopping": []}

    def list_task_columns(self, *, chat_id: int, user_id: int, include_done: bool = False):
        del chat_id, user_id, include_done
        return [
            KbplusColumn(
                id="todo",
                name="Todo",
                is_done=False,
                tasks=[KbplusTask(id="tsk_1", title="Buy apples", description=None, column_id="todo", column_name="Todo")],
            ),
            KbplusColumn(
                id="doing",
                name="Doing",
                is_done=False,
                tasks=[KbplusTask(id="tsk_2", title="Call bank", description=None, column_id="doing", column_name="Doing")],
            ),
        ]

    def create_pending_approval(self, *, chat_id: int, user_id: int, action_type: str, payload: dict, prompt_text: str):
        del chat_id, user_id
        self.pending_calls.append({"action_type": action_type, "payload": payload, "prompt_text": prompt_text})
        return PendingApproval(token="abc123", prompt_text=prompt_text or "Auto prompt", expires_at="2026-04-01T12:00:00+00:00")

    def create_pending_tool_plan(self, *, chat_id: int, user_id: int, steps: list[dict], prompt_text: str = ""):
        del chat_id, user_id, prompt_text
        self.pending_calls.append({"action_type": "tool_plan", "payload": {"steps": steps}, "prompt_text": "2 planned actions"})
        return PendingApproval(token="abc123", prompt_text="2 planned actions", expires_at="2026-04-01T12:00:00+00:00")

    def parse_flexible_local_datetime(self, *, chat_id: int, user_id: int, raw_text: str):
        del chat_id, user_id
        if raw_text == "tomorrow 09:30":
            return datetime(2026, 4, 2, 9, 30, tzinfo=timezone.utc)
        return datetime.strptime(raw_text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)

    def list_calendar_events_between(self, *, chat_id: int, user_id: int, start_local: datetime, end_local: datetime):
        del chat_id, user_id
        self.between_calls.append((start_local, end_local))
        return [
            type(
                "Event",
                (),
                {
                    "summary": "Standup",
                    "start": datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc),
                    "end": datetime(2026, 4, 2, 10, 30, tzinfo=timezone.utc),
                },
            )
        ]

    def confirm_approval(self, *, chat_id: int, user_id: int, token: str) -> str:
        self.confirm_calls.append((chat_id, user_id, token))
        return "Created task."

    def reject_approval(self, *, chat_id: int, user_id: int, token: str) -> str:
        self.reject_calls.append((chat_id, user_id, token))
        return "Rejected pending action abc123"

    def complete_item(self, *, chat_id: int, user_id: int, kind: str, item_id: str | int) -> None:
        self.completed_calls.append((chat_id, user_id, kind, item_id))

    def rename_item(self, *, chat_id: int, user_id: int, kind: str, item_id: str | int, title: str) -> None:
        self.renamed_calls.append((chat_id, user_id, kind, item_id, title))


class FakeAIClient:
    configured = True

    async def respond(self, *, user_message: str, history, tool_snapshot):
        del history, tool_snapshot
        return AIResponse(
            reply=f"I can do that for: {user_message}",
            tool_plan=[
                {"tool": "tasks", "operation": "create", "args": {"title": "Buy apples"}},
                {"tool": "tasks", "operation": "create", "args": {"title": "Buy pears"}},
            ],
        )


class FakeDeleteNoteAIClient:
    configured = True

    async def respond(self, *, user_message: str, history, tool_snapshot):
        del user_message, history, tool_snapshot
        return AIResponse(
            reply="I prepared a request for confirmation.",
            tool_plan=[{"tool": "notes", "operation": "delete", "args": {}}],
        )


class FakeNoteDeleteAssistant(FakeAssistant):
    def __init__(self):
        super().__init__()
        self.notes = [type("Note", (), {"id": 7, "kind": "note", "content": "Buy milk"})()]

    def create_pending_tool_plan(self, *, chat_id: int, user_id: int, steps: list[dict], prompt_text: str = ""):
        del chat_id, user_id, steps, prompt_text
        raise AssistantError("Note delete operation is missing note_id")

    def list_notes(self, *, chat_id: int, user_id: int, limit: int = 10, query: str | None = None):
        del chat_id, user_id, limit, query
        return list(self.notes)


def test_task_handler_lists_grouped_columns(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )
    message = FakeMessage(text="")
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))
    context = FakeContext(bot=FakeBot(), args=["list"])

    asyncio.run(bot.task_handler(update, context))

    assert message.replies[0]["text"] == "Open tasks:\nTodo\n- 1. Buy apples\n\nDoing\n- 2. Call bank"


def test_task_done_resolves_numeric_reference_for_kbplus(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )
    message = FakeMessage(text="")
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.task_handler(update, FakeContext(bot=FakeBot(), args=["done", "2"])))

    assert assistant.completed_calls == [(10, 20, "task", "tsk_2")]
    assert message.replies[0]["text"] == "Marked task 2 complete"


def test_task_done_resolves_numeric_reference_for_local_tasks(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    assistant.kbplus = None

    def local_columns(*, chat_id: int, user_id: int, include_done: bool = False):
        del chat_id, user_id, include_done
        return [
            KbplusColumn(
                id="local-open",
                name="Open tasks",
                is_done=False,
                tasks=[
                    KbplusTask(id="41", title="Buy apples", description=None, column_id="local-open", column_name="Open tasks"),
                    KbplusTask(id="77", title="Call bank", description=None, column_id="local-open", column_name="Open tasks"),
                ],
            )
        ]

    assistant.list_task_columns = local_columns
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )
    message = FakeMessage(text="")
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.task_handler(update, FakeContext(bot=FakeBot(), args=["done", "2"])))

    assert assistant.completed_calls == [(10, 20, "task", "77")]
    assert message.replies[0]["text"] == "Marked task 2 complete"


def test_task_rename_resolves_numeric_reference_for_kbplus(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )
    message = FakeMessage(text="")
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.task_handler(update, FakeContext(bot=FakeBot(), args=["rename", "1", "|", "Buy green apples"])))

    assert assistant.renamed_calls == [(10, 20, "task", "tsk_1", "Buy green apples")]
    assert message.replies[0]["text"] == "Renamed task 1"


def test_task_done_keeps_raw_non_numeric_identifier_compatible(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )
    message = FakeMessage(text="")
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.task_handler(update, FakeContext(bot=FakeBot(), args=["done", "tsk_2"])))

    assert assistant.completed_calls == [(10, 20, "task", "tsk_2")]
    assert message.replies[0]["text"] == "Marked task tsk_2 complete"


class FakeSpeechToText:
    def unavailable_message(self):
        return None

    async def transcribe_file(self, audio_path):
        del audio_path
        return TranscriptionResult(text="hello")


def test_chat_handler_sends_inline_approval_buttons(tmp_path: Path) -> None:
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path),
        assistant=FakeAssistant(),
        ai_client=FakeAIClient(),
        transcriber=FakeSpeechToText(),
    )
    message = FakeMessage(text="add buy apples to my tasks")
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))
    context = FakeContext(bot=FakeBot())

    asyncio.run(bot.chat_handler(update, context))

    assert len(message.replies) == 1
    reply = message.replies[0]
    assert "I can do that for:" not in reply["text"]
    assert reply["text"].startswith("Please confirm this request.")
    assert "Proposed action: 2 planned actions" in reply["text"]
    markup = reply["reply_markup"]
    assert markup is not None
    first_row = markup.inline_keyboard[0]
    assert first_row[0].callback_data == "approve:abc123"
    assert first_row[1].callback_data == "reject:abc123"


def test_chat_handler_note_delete_fallback_creates_confirmation_after_id_reply(tmp_path: Path) -> None:
    assistant = FakeNoteDeleteAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path),
        assistant=assistant,
        ai_client=FakeDeleteNoteAIClient(),
        transcriber=FakeSpeechToText(),
    )
    context = FakeContext(bot=FakeBot())

    first_message = FakeMessage(text="delete the buy milk note")
    first_update = FakeUpdate(effective_message=first_message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.chat_handler(first_update, context))

    assert len(first_message.replies) == 1
    assert first_message.replies[0]["text"].startswith(
        "I understood this as a note deletion request, but I couldn't prepare the confirmation yet."
    )
    assert "#7 [note] Buy milk" in first_message.replies[0]["text"]

    second_message = FakeMessage(text="#7")
    second_update = FakeUpdate(effective_message=second_message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.chat_handler(second_update, context))

    assert assistant.pending_calls[-1] == {
        "action_type": "delete_note",
        "payload": {"note_id": 7},
        "prompt_text": "",
    }
    assert second_message.replies[0]["text"].startswith("Please confirm this request.")


def test_approval_callback_handler_confirms_action(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )
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
    assert query.edits == ["✅ Approved — Created task."]


def test_approval_callback_handler_rejects_action(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )
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
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path), assistant=FakeAssistant(), ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )

    assert bot._parse_approval_callback_data("approve:abc123") == ("approve", "abc123")
    assert bot._parse_approval_callback_data("reject:abc123") == ("reject", "abc123")
    assert bot._parse_approval_callback_data("approve:not valid") is None
    assert bot._parse_approval_callback_data("random") is None


def test_approval_callback_handler_respects_allowed_chat_ids(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "allowed_chat_ids": frozenset({999})})
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=settings, assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )
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


def test_reminder_add_interactive_flow_creates_pending_approval(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path),
        assistant=assistant,
        ai_client=FakeAIClient(),
        transcriber=FakeSpeechToText(),
    )

    start_message = FakeMessage()
    start_update = FakeUpdate(effective_message=start_message, effective_chat=FakeChat(10), effective_user=FakeUser(20))
    asyncio.run(bot.reminder_handler(start_update, FakeContext(bot=FakeBot(), args=["add"])))
    assert start_message.replies[0]["text"] == "What should I remind you about? Use /cancel to stop."

    message_step = FakeMessage(text="Call mom")
    message_update = FakeUpdate(effective_message=message_step, effective_chat=FakeChat(10), effective_user=FakeUser(20))
    asyncio.run(bot.chat_handler(message_update, FakeContext(bot=FakeBot())))
    assert "When should I remind you?" in message_step.replies[0]["text"]

    when_step = FakeMessage(text="tomorrow 09:30")
    when_update = FakeUpdate(effective_message=when_step, effective_chat=FakeChat(10), effective_user=FakeUser(20))
    asyncio.run(bot.chat_handler(when_update, FakeContext(bot=FakeBot())))

    assert assistant.pending_calls[-1]["action_type"] == "create_reminder"
    assert assistant.pending_calls[-1]["payload"] == {"when_local": "2026-04-02 09:30", "message": "Call mom"}
    assert when_step.replies[0]["text"].startswith("Please confirm this request.")


def test_calendar_tomorrow_formats_window_and_event_list(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path),
        assistant=assistant,
        ai_client=FakeAIClient(),
        transcriber=FakeSpeechToText(),
    )

    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))
    asyncio.run(bot.calendar_handler(update, FakeContext(bot=FakeBot(), args=["tomorrow"])))

    assert assistant.between_calls, "expected calendar window call"
    start_local, end_local = assistant.between_calls[0]
    assert (end_local - start_local).days == 1
    assert message.replies[0]["text"].startswith("Tomorrow:")
    assert "Standup" in message.replies[0]["text"]


def test_recover_approval_from_history_ignores_confirmation_prompts(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path), assistant=assistant, ai_client=FakeAIClient(), transcriber=FakeSpeechToText()
    )

    history = [type("Msg", (), {"role": "assistant", "content": "Please confirm this request.\n\nProposed action: ..."})]

    recovered = bot._recover_approval_from_history(chat_id=10, user_id=20, history=history)

    assert recovered is None
    assert assistant.pending_calls == []
