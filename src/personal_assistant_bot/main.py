from __future__ import annotations

import logging
import sys

from personal_assistant_bot.ai import OpenAICompatibleAI
from personal_assistant_bot.bot import PersonalAssistantBot
from personal_assistant_bot.calendar_integration import CalendarService
from personal_assistant_bot.config import ConfigurationError, load_settings
from personal_assistant_bot.kbplus_integration import KbplusTaskClient
from personal_assistant_bot.services import AssistantService
from personal_assistant_bot.speech import LocalSpeechTranscriber
from personal_assistant_bot.storage import SQLiteStorage


def main() -> None:
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

    storage = SQLiteStorage(settings.database_path)
    calendar_service = CalendarService(
        url=settings.caldav_url,
        username=settings.caldav_username,
        password=settings.caldav_password,
        calendar_name=settings.caldav_calendar_name,
    )
    kbplus_client = KbplusTaskClient(
        base_url=settings.kbplus_base_url,
        api_token=settings.kbplus_api_token,
        board_id=settings.kbplus_board_id,
        todo_column_id=settings.kbplus_todo_column_id,
        done_column_id=settings.kbplus_done_column_id,
        timeout_seconds=settings.kbplus_timeout_seconds,
    )
    assistant = AssistantService(storage=storage, calendar=calendar_service, settings=settings, kbplus=kbplus_client)
    ai_client = OpenAICompatibleAI(
        base_url=settings.backend_base_url,
        api_key=settings.backend_api_key,
        model=settings.backend_model,
        timeout_seconds=settings.backend_timeout_seconds,
    )
    transcriber = LocalSpeechTranscriber(
        enabled=settings.stt_enabled,
        model_name=settings.stt_model,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
        language=settings.stt_language,
        vad_filter=settings.stt_vad_filter,
        model_dir=settings.stt_model_dir,
    )
    bot = PersonalAssistantBot(settings=settings, assistant=assistant, ai_client=ai_client, transcriber=transcriber)
    application = bot.build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
