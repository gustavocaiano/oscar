from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from personal_assistant_bot.ai import AIResponse
from personal_assistant_bot.bot import PersonalAssistantBot
from personal_assistant_bot.config import Settings
from personal_assistant_bot.speech import SpeechToTextFailedError, TranscriptionResult


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
        stt_enabled=True,
        stt_echo_transcript=True,
        stt_max_duration_seconds=60,
        stt_max_file_size_mb=10,
    )


@dataclass
class FakeUser:
    id: int


@dataclass
class FakeChat:
    id: int


@dataclass
class FakeVoice:
    duration: int
    file_size: int | None
    file_unique_id: str
    mime_type: str | None = "audio/ogg"


@dataclass
class FakeAudio:
    duration: int
    file_size: int | None
    file_unique_id: str
    mime_type: str | None = "audio/mp4"


class FakeTelegramFile:
    def __init__(self, payload: bytes = b"voice-bytes"):
        self.saved_paths: list[Path] = []
        self.payload = payload

    async def download_to_drive(self, custom_path: str):
        path = Path(custom_path)
        path.write_bytes(self.payload)
        self.saved_paths.append(path)


class FakeAttachment:
    def __init__(self, telegram_file: FakeTelegramFile):
        self.telegram_file = telegram_file

    async def get_file(self):
        return self.telegram_file


class FakeMessage:
    def __init__(self, *, chat_id: int, voice=None, audio=None, attachment=None):
        self.text = None
        self.chat_id = chat_id
        self.voice = voice
        self.audio = audio
        self.effective_attachment = attachment
        self.replies: list[dict[str, object]] = []

    async def reply_text(self, text: str, reply_markup=None):
        self.replies.append({"text": text, "reply_markup": reply_markup})


@dataclass
class FakeUpdate:
    effective_message: FakeMessage | None
    effective_chat: FakeChat | None
    effective_user: FakeUser | None
    callback_query: None = None


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

    def ensure_chat(self, *, chat_id: int, user_id: int):
        return None

    def add_chat_history(self, *, chat_id: int, user_id: int, role: str, content: str) -> None:
        self.chat_history.append((chat_id, user_id, role, content))

    def get_chat_history(self, *, chat_id: int, user_id: int):
        return []

    def get_tool_snapshot(self, *, chat_id: int, user_id: int):
        return {"tasks": [], "shopping": [], "reminders": []}

    def create_pending_approval(self, *, chat_id: int, user_id: int, action_type: str, payload: dict, prompt_text: str):
        raise AssertionError("Voice routing test should not create approval here")


class FakeAIClient:
    configured = True

    async def respond(self, *, user_message: str, history, tool_snapshot, read_only_tool_executor=None):
        del history, tool_snapshot, read_only_tool_executor
        return AIResponse(reply=f"Reply for: {user_message}", proposed_action=None)


class FakeSpeechToText:
    def __init__(self, *, unavailable_message: str | None = None, failure_message: str | None = None):
        self._unavailable_message = unavailable_message
        self.failure_message = failure_message
        self.transcribed_paths: list[Path] = []

    def unavailable_message(self):
        return self._unavailable_message

    async def transcribe_file(self, audio_path: Path):
        self.transcribed_paths.append(audio_path)
        if self.failure_message is not None:
            raise SpeechToTextFailedError(self.failure_message)
        assert audio_path.exists()
        return TranscriptionResult(text="comprar pão", language="pt", duration_seconds=4.0)


def test_voice_handler_routes_transcript_into_ai_flow_and_cleans_tempfile(tmp_path: Path) -> None:
    assistant = FakeAssistant()
    transcriber = FakeSpeechToText()
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path),
        assistant=assistant,
        ai_client=FakeAIClient(),
        transcriber=transcriber,
    )
    telegram_file = FakeTelegramFile()
    message = FakeMessage(
        chat_id=10,
        voice=FakeVoice(duration=12, file_size=1000, file_unique_id="voice-1"),
        attachment=FakeAttachment(telegram_file),
    )
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.voice_handler(update, FakeContext(bot=FakeBot())))

    assert assistant.chat_history[0] == (10, 20, "user", "comprar pão")
    assert assistant.chat_history[1] == (10, 20, "assistant", "Reply for: comprar pão")
    assert 'Heard: "comprar pão"' in message.replies[0]["text"]
    assert "Reply for: comprar pão" in message.replies[0]["text"]
    assert transcriber.transcribed_paths[0].exists() is False


def test_voice_handler_rejects_oversized_voice_note(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "stt_max_duration_seconds": 30})
    bot = PersonalAssistantBot(
        settings=settings,
        assistant=FakeAssistant(),
        ai_client=FakeAIClient(),
        transcriber=FakeSpeechToText(),
    )
    message = FakeMessage(
        chat_id=10,
        voice=FakeVoice(duration=90, file_size=1000, file_unique_id="voice-2"),
        attachment=FakeAttachment(FakeTelegramFile()),
    )
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.voice_handler(update, FakeContext(bot=FakeBot())))

    assert "longer than 30s" in message.replies[0]["text"]


def test_voice_handler_reports_unavailable_transcription(tmp_path: Path) -> None:
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path),
        assistant=FakeAssistant(),
        ai_client=FakeAIClient(),
        transcriber=FakeSpeechToText(
            unavailable_message="Local voice transcription is not enabled for this assistant."
        ),
    )
    message = FakeMessage(
        chat_id=10,
        voice=FakeVoice(duration=10, file_size=1000, file_unique_id="voice-3"),
        attachment=FakeAttachment(FakeTelegramFile()),
    )
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.voice_handler(update, FakeContext(bot=FakeBot())))

    assert message.replies[0]["text"] == "Local voice transcription is not enabled for this assistant."


def test_voice_handler_enforces_post_download_file_size_limit(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings = Settings(**{**settings.__dict__, "stt_max_file_size_mb": 1})
    bot = PersonalAssistantBot(
        settings=settings,
        assistant=FakeAssistant(),
        ai_client=FakeAIClient(),
        transcriber=FakeSpeechToText(),
    )
    large_payload = b"x" * (2 * 1024 * 1024)
    message = FakeMessage(
        chat_id=10,
        voice=FakeVoice(duration=10, file_size=None, file_unique_id="voice-oversize"),
        attachment=FakeAttachment(FakeTelegramFile(payload=large_payload)),
    )
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.voice_handler(update, FakeContext(bot=FakeBot())))

    assert "larger than 1 MB" in message.replies[0]["text"]


def test_voice_handler_reports_transcription_failure(tmp_path: Path) -> None:
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path),
        assistant=FakeAssistant(),
        ai_client=FakeAIClient(),
        transcriber=FakeSpeechToText(failure_message="Transcription failed: decoder error"),
    )
    message = FakeMessage(
        chat_id=10,
        voice=FakeVoice(duration=10, file_size=1000, file_unique_id="voice-4"),
        attachment=FakeAttachment(FakeTelegramFile()),
    )
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.voice_handler(update, FakeContext(bot=FakeBot())))

    assert message.replies[0]["text"] == "Transcription failed: decoder error"


def test_audio_handler_explains_voice_only_scope(tmp_path: Path) -> None:
    bot = PersonalAssistantBot(
        settings=build_settings(tmp_path),
        assistant=FakeAssistant(),
        ai_client=FakeAIClient(),
        transcriber=FakeSpeechToText(),
    )
    message = FakeMessage(chat_id=10, audio=FakeAudio(duration=20, file_size=3000, file_unique_id="audio-1"))
    update = FakeUpdate(effective_message=message, effective_chat=FakeChat(10), effective_user=FakeUser(20))

    asyncio.run(bot.unsupported_audio_handler(update, FakeContext(bot=FakeBot())))

    assert "voice notes are supported" in message.replies[0]["text"]
