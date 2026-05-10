from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from personal_assistant_bot.ai import AIBackendError, AIResponse
from personal_assistant_bot.bible_integration import BibleChapter, BibleIntegrationError, BibleVerse
from personal_assistant_bot.bot import PersonalAssistantBot
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
            verses=[
                BibleVerse(number=1, text="No princípio Deus criou os céus e a terra."),
                BibleVerse(number=2, text="A terra era sem forma e vazia."),
            ],
        )


class FailingBibleClient:
    configured = True

    async def fetch_chapter(self, *, translation: str, book_abbrev: str, chapter: int) -> BibleChapter:
        del translation, book_abbrev, chapter
        raise BibleIntegrationError("provider down")


class FakeDisabledAI:
    configured = False


class FakeResumeAI:
    configured = True

    async def respond(self, *, user_message: str, history, tool_snapshot, read_only_tool_executor=None):
        del user_message, history, tool_snapshot, read_only_tool_executor
        return AIResponse(reply="Resumo curto em português.")


class FakeFailingAI:
    configured = True

    async def respond(self, *, user_message: str, history, tool_snapshot, read_only_tool_executor=None):
        del user_message, history, tool_snapshot, read_only_tool_executor
        raise AIBackendError("AI down")


class FakeActionAI:
    configured = True

    async def respond(self, *, user_message: str, history, tool_snapshot, read_only_tool_executor=None):
        del user_message, history, tool_snapshot, read_only_tool_executor
        return AIResponse(
            reply="Resumo que deve ser ignorado.",
            tool_plan=[{"tool": "tasks", "operation": "create", "args": {"title": "Não usar"}}],
        )


class FakeSpeechToText:
    def unavailable_message(self):
        return "STT disabled"


def build_settings(tmp_path: Path, *, bible_enabled: bool = True) -> Settings:
    base = Settings(
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
    return replace(base, bible_enabled=bible_enabled, bible_daily_time="09:00")


def build_service(tmp_path: Path, *, bible_enabled: bool = True, bible=None) -> AssistantService:
    settings = build_settings(tmp_path, bible_enabled=bible_enabled)
    storage = SQLiteStorage(settings.database_path)
    return AssistantService(
        storage=storage,
        calendar=FakeCalendarService(),
        settings=settings,
        bible=bible or FakeBibleClient(),
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
        self.sent_messages: list[dict[str, object]] = []

    async def send_message(self, *, chat_id: int, text: str, reply_markup=None):
        self.sent_messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})


@dataclass
class FakeContext:
    bot: FakeBot
    args: list[str] | None = None

    def __post_init__(self) -> None:
        if self.args is None:
            self.args = []


def build_bot(tmp_path: Path, *, service: AssistantService, ai_client=None, settings: Settings | None = None):
    return PersonalAssistantBot(
        settings=settings or service.settings,
        assistant=service,
        ai_client=ai_client or FakeDisabledAI(),
        transcriber=FakeSpeechToText(),
    )


def test_bible_raw_formatting_and_long_message_splitting(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    delivery = asyncio.run(service.prepare_next_bible_chapter(chat_id=1, user_id=2))

    text = service.format_bible_chapter_text(delivery, resume="Resumo direto.")
    chunks = service.split_bible_message(text, limit=45)

    assert "📖 Gênesis 1 (NVI)" in text
    assert "Resumo:\nResumo direto." in text
    assert "1. No princípio" in text
    assert len(chunks) > 1
    assert all(len(chunk) <= 45 for chunk in chunks)


def test_bible_split_handles_empty_and_very_long_single_line(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    assert service.split_bible_message("") == [""]
    assert service.split_bible_message("abcde", limit=5) == ["abcde"]
    assert service.split_bible_message("abcdefghij", limit=4) == ["abcd", "efgh", "ij"]


def test_bible_provider_failure_does_not_advance_progress(tmp_path: Path) -> None:
    service = build_service(tmp_path, bible=FailingBibleClient())

    with pytest.raises(AssistantError):
        asyncio.run(service.prepare_next_bible_chapter(chat_id=1, user_id=2))

    progress = service.storage.get_bible_progress(chat_id=1)
    assert progress is not None
    assert (progress.next_book, progress.next_chapter, progress.chapters_read) == ("gn", 1, 0)


def test_prepare_next_bible_chapter_rejects_completed_reading(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.ensure_chat(chat_id=1, user_id=2)
    service.storage.set_bible_progress(
        chat_id=1,
        user_id=2,
        translation="nvi",
        next_book=None,
        next_chapter=None,
        completed_at="2026-04-01T00:00:00+00:00",
    )

    with pytest.raises(AssistantError, match="concluída"):
        asyncio.run(service.prepare_next_bible_chapter(chat_id=1, user_id=2))


def test_mark_bible_chapter_delivered_rejects_double_advance(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    delivery = asyncio.run(service.prepare_next_bible_chapter(chat_id=1, user_id=2))

    service.mark_bible_chapter_delivered(delivery)

    with pytest.raises(AssistantError, match="progresso mudou"):
        service.mark_bible_chapter_delivered(delivery)


def test_bible_command_status_and_read_next_chapter(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    bot = build_bot(tmp_path, service=service)
    fake_bot = FakeBot()
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.bible_handler(update, FakeContext(bot=fake_bot, args=[])))
    asyncio.run(bot.bible_handler(update, FakeContext(bot=fake_bot, args=["ler"])))

    assert "Próximo capítulo: Gênesis 1" in str(message.replies[0]["text"])
    assert "Gênesis 1" in str(fake_bot.sent_messages[0]["text"])
    progress = service.storage.get_bible_progress(chat_id=10)
    assert progress is not None
    assert (progress.next_book, progress.next_chapter) == ("gn", 2)


def test_bible_command_unknown_subcommand(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    bot = build_bot(tmp_path, service=service)
    message = FakeMessage()
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.bible_handler(update, FakeContext(bot=FakeBot(), args=["foo"])))

    assert message.replies[0]["text"] == "Comandos: /biblia · /biblia ler"


def test_bible_callback_read_sends_one_chapter_and_advances(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    bot = build_bot(tmp_path, service=service)
    fake_bot = FakeBot()
    query = FakeCallbackQuery("bible:read")
    update = FakeUpdate(
        effective_message=None,
        effective_chat=FakeChat(10),
        effective_user=FakeUser(20),
        callback_query=query,
    )

    asyncio.run(bot.bible_callback_handler(update, FakeContext(bot=fake_bot)))

    assert len(fake_bot.sent_messages) == 1
    assert "Gênesis 1" in str(fake_bot.sent_messages[0]["text"])
    assert query.answers[-1] == {"text": "Capítulo enviado.", "show_alert": False}
    assert query.edits == ["📖 Capítulo enviado. Amanhã eu te lembro de novo."]
    progress = service.storage.get_bible_progress(chat_id=10)
    assert progress is not None
    assert (progress.next_book, progress.next_chapter) == ("gn", 2)


def test_bible_callback_dismiss_does_not_send_or_advance(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    service.ensure_chat(chat_id=10, user_id=20)
    service.storage.ensure_bible_progress(chat_id=10, user_id=20, translation="nvi")
    bot = build_bot(tmp_path, service=service)
    fake_bot = FakeBot()
    query = FakeCallbackQuery("bible:dismiss")
    update = FakeUpdate(
        effective_message=None,
        effective_chat=FakeChat(10),
        effective_user=FakeUser(20),
        callback_query=query,
    )

    asyncio.run(bot.bible_callback_handler(update, FakeContext(bot=fake_bot)))

    assert fake_bot.sent_messages == []
    assert query.edits == ["📖 Tudo bem — te lembro amanhã."]
    progress = service.storage.get_bible_progress(chat_id=10)
    assert progress is not None
    assert (progress.next_book, progress.next_chapter) == ("gn", 1)


def test_disabled_bible_callback_rejects_without_sending(tmp_path: Path) -> None:
    service = build_service(tmp_path, bible_enabled=False)
    bot = build_bot(tmp_path, service=service)
    fake_bot = FakeBot()
    query = FakeCallbackQuery("bible:read")
    update = FakeUpdate(
        effective_message=None,
        effective_chat=FakeChat(10),
        effective_user=FakeUser(20),
        callback_query=query,
    )

    asyncio.run(bot.bible_callback_handler(update, FakeContext(bot=fake_bot)))

    assert fake_bot.sent_messages == []
    assert query.answers[-1] == {"text": "Leitura bíblica não configurada.", "show_alert": True}


def test_bible_ai_resume_success_is_included(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    bot = build_bot(tmp_path, service=service, ai_client=FakeResumeAI())
    fake_bot = FakeBot()

    asyncio.run(bot._send_next_bible_chapter(chat_id=10, user_id=20, context=FakeContext(bot=fake_bot)))

    assert "Resumo curto em português." in str(fake_bot.sent_messages[0]["text"])
    assert "No princípio" in str(fake_bot.sent_messages[0]["text"])


def test_bible_ai_resume_failure_falls_back_to_raw_text(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    bot = build_bot(tmp_path, service=service, ai_client=FakeFailingAI())
    fake_bot = FakeBot()

    asyncio.run(bot._send_next_bible_chapter(chat_id=10, user_id=20, context=FakeContext(bot=fake_bot)))

    text = str(fake_bot.sent_messages[0]["text"])
    assert "Resumo:" not in text
    assert "No princípio" in text


def test_bible_ai_proposed_action_is_ignored(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    bot = build_bot(tmp_path, service=service, ai_client=FakeActionAI())
    fake_bot = FakeBot()

    asyncio.run(bot._send_next_bible_chapter(chat_id=10, user_id=20, context=FakeContext(bot=fake_bot)))

    text = str(fake_bot.sent_messages[0]["text"])
    assert "Resumo que deve ser ignorado" not in text
    assert "No princípio" in text


def test_scheduler_tick_sends_bible_prompt_keyboard(tmp_path: Path) -> None:
    settings = replace(build_settings(tmp_path), bible_enabled=True, bible_daily_time="00:00")
    storage = SQLiteStorage(settings.database_path)
    service = AssistantService(
        storage=storage,
        calendar=FakeCalendarService(),
        settings=settings,
        bible=FakeBibleClient(),
    )
    service.ensure_chat(chat_id=10, user_id=20)
    bot = build_bot(tmp_path, service=service)
    fake_bot = FakeBot()

    asyncio.run(bot.scheduler_tick(FakeContext(bot=fake_bot)))

    bible_messages = [message for message in fake_bot.sent_messages if "Bíblia" in str(message["text"])]
    assert len(bible_messages) == 1
    assert bible_messages[0]["reply_markup"] is not None
