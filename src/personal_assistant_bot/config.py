from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when the runtime configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    allowed_chat_ids: frozenset[int]
    database_path: Path
    backend_base_url: str | None
    backend_api_key: str | None
    backend_model: str | None
    backend_timeout_seconds: float
    chat_history_limit: int
    approval_ttl_minutes: int
    default_timezone: str
    morning_brief_time: str
    hour_reminder_time: str
    evening_wrap_up_time: str
    reminder_scan_seconds: int
    caldav_url: str | None
    caldav_username: str | None
    caldav_password: str | None
    caldav_calendar_name: str | None
    log_level: int
    stt_enabled: bool = False
    stt_model: str = "base"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    stt_language: str | None = None
    stt_vad_filter: bool = True
    stt_max_duration_seconds: int = 60
    stt_max_file_size_mb: int = 10
    stt_model_dir: Path = Path("/models/whisper")
    stt_echo_transcript: bool = True
    kbplus_base_url: str | None = None
    kbplus_api_token: str | None = None
    kbplus_board_id: str | None = None
    kbplus_todo_column_id: str | None = None
    kbplus_done_column_id: str | None = None
    kbplus_timeout_seconds: float = 10.0
    bible_enabled: bool = False
    bible_api_base_url: str = "https://www.abibliadigital.com.br/api"
    bible_api_token: str | None = None
    bible_translation: str = "nvi"
    bible_daily_time: str = "09:00"
    bible_timeout_seconds: float = 10.0

    @property
    def backend_enabled(self) -> bool:
        return bool(self.backend_base_url and self.backend_api_key and self.backend_model)

    @property
    def caldav_enabled(self) -> bool:
        return bool(self.caldav_url and self.caldav_username and self.caldav_password)

    @property
    def kbplus_enabled(self) -> bool:
        return bool(
            self.kbplus_base_url
            and self.kbplus_api_token
            and self.kbplus_board_id
            and self.kbplus_todo_column_id
            and self.kbplus_done_column_id
        )

    @property
    def bible_configured(self) -> bool:
        return bool(self.bible_enabled and self.bible_api_base_url and self.bible_translation)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"Environment variable {name} must be an integer") from exc


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigurationError(f"Environment variable {name} must be a number") from exc


def _parse_allowed_chat_ids(raw_value: str | None) -> frozenset[int]:
    if not raw_value:
        return frozenset()

    ids: set[int] = set()
    for part in raw_value.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        try:
            ids.add(int(stripped))
        except ValueError as exc:
            raise ConfigurationError("ALLOWED_CHAT_IDS must be a comma-separated list of numeric chat ids") from exc
    return frozenset(ids)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"Environment variable {name} must be a boolean")


def _bible_translation_env(name: str, default: str) -> str:
    translation = os.getenv(name, default).strip().lower() or default
    if translation not in {"nvi", "acf", "ra", "arc"}:
        raise ConfigurationError(f"Environment variable {name} must be one of: nvi, acf, ra, arc")
    return translation


def load_settings() -> Settings:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    log_level = getattr(logging, log_level_name, None)
    if not isinstance(log_level, int):
        raise ConfigurationError("LOG_LEVEL must be a valid Python logging level name")

    return Settings(
        telegram_bot_token=_required_env("TELEGRAM_BOT_TOKEN"),
        allowed_chat_ids=_parse_allowed_chat_ids(_optional_env("ALLOWED_CHAT_IDS")),
        database_path=Path(os.getenv("DATABASE_PATH", "/data/assistant.sqlite3")).expanduser(),
        backend_base_url=_optional_env("BACKEND_BASE_URL"),
        backend_api_key=_optional_env("BACKEND_API_KEY"),
        backend_model=_optional_env("BACKEND_MODEL"),
        backend_timeout_seconds=max(1.0, _float_env("BACKEND_TIMEOUT_SECONDS", 60.0)),
        chat_history_limit=max(1, _int_env("CHAT_HISTORY_LIMIT", 12)),
        approval_ttl_minutes=max(1, _int_env("APPROVAL_TTL_MINUTES", 30)),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "UTC").strip() or "UTC",
        morning_brief_time=os.getenv("MORNING_BRIEF_TIME", "08:00").strip() or "08:00",
        hour_reminder_time=os.getenv("HOUR_REMINDER_TIME", "18:00").strip() or "18:00",
        evening_wrap_up_time=os.getenv("EVENING_WRAP_UP_TIME", "20:00").strip() or "20:00",
        reminder_scan_seconds=max(15, _int_env("REMINDER_SCAN_SECONDS", 60)),
        caldav_url=_optional_env("CALDAV_URL"),
        caldav_username=_optional_env("CALDAV_USERNAME"),
        caldav_password=_optional_env("CALDAV_PASSWORD"),
        caldav_calendar_name=_optional_env("CALDAV_CALENDAR_NAME"),
        log_level=log_level,
        stt_enabled=_bool_env("STT_ENABLED", False),
        stt_model=os.getenv("STT_MODEL", "base").strip() or "base",
        stt_device=os.getenv("STT_DEVICE", "cpu").strip() or "cpu",
        stt_compute_type=os.getenv("STT_COMPUTE_TYPE", "int8").strip() or "int8",
        stt_language=_optional_env("STT_LANGUAGE"),
        stt_vad_filter=_bool_env("STT_VAD_FILTER", True),
        stt_max_duration_seconds=max(1, _int_env("STT_MAX_DURATION_SECONDS", 60)),
        stt_max_file_size_mb=max(1, _int_env("STT_MAX_FILE_SIZE_MB", 10)),
        stt_model_dir=Path(os.getenv("STT_MODEL_DIR", "/models/whisper")).expanduser(),
        stt_echo_transcript=_bool_env("STT_ECHO_TRANSCRIPT", True),
        kbplus_base_url=_optional_env("KBPLUS_BASE_URL"),
        kbplus_api_token=_optional_env("KBPLUS_API_TOKEN"),
        kbplus_board_id=_optional_env("KBPLUS_BOARD_ID"),
        kbplus_todo_column_id=_optional_env("KBPLUS_TODO_COLUMN_ID"),
        kbplus_done_column_id=_optional_env("KBPLUS_DONE_COLUMN_ID"),
        kbplus_timeout_seconds=max(1.0, _float_env("KBPLUS_TIMEOUT_SECONDS", 10.0)),
        bible_enabled=_bool_env("BIBLE_ENABLED", False),
        bible_api_base_url=(
            os.getenv("BIBLE_API_BASE_URL", "https://www.abibliadigital.com.br/api").strip()
            or "https://www.abibliadigital.com.br/api"
        ),
        bible_api_token=_optional_env("BIBLE_API_TOKEN"),
        bible_translation=_bible_translation_env("BIBLE_TRANSLATION", "nvi"),
        bible_daily_time=os.getenv("BIBLE_DAILY_TIME", "09:00").strip() or "09:00",
        bible_timeout_seconds=max(1.0, _float_env("BIBLE_TIMEOUT_SECONDS", 10.0)),
    )
