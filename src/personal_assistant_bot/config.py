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

    @property
    def backend_enabled(self) -> bool:
        return bool(self.backend_base_url and self.backend_api_key and self.backend_model)

    @property
    def caldav_enabled(self) -> bool:
        return bool(self.caldav_url and self.caldav_username and self.caldav_password)


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
            raise ConfigurationError(
                "ALLOWED_CHAT_IDS must be a comma-separated list of numeric chat ids"
            ) from exc
    return frozenset(ids)


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
    )
