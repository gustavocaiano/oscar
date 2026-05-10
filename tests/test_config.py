from __future__ import annotations

import logging

import pytest

from personal_assistant_bot.config import (
    ConfigurationError,
    Settings,
    _bible_translation_env,
    _bool_env,
    _float_env,
    _int_env,
    _optional_env,
    _parse_allowed_chat_ids,
    _required_env,
    load_settings,
)

# ---------------------------------------------------------------------------
# 1. ConfigurationError is a ValueError subclass
# ---------------------------------------------------------------------------


def test_configuration_error_is_value_error():
    assert issubclass(ConfigurationError, ValueError)


def test_configuration_error_message():
    err = ConfigurationError("bad config")
    assert str(err) == "bad config"


# ---------------------------------------------------------------------------
# 2. _required_env
# ---------------------------------------------------------------------------


def test_required_env_with_set_value(monkeypatch):
    monkeypatch.setenv("TEST_REQ", "hello")
    assert _required_env("TEST_REQ") == "hello"


def test_required_env_strips_whitespace(monkeypatch):
    monkeypatch.setenv("TEST_REQ", "  hello  ")
    assert _required_env("TEST_REQ") == "hello"


def test_required_env_empty_string_raises(monkeypatch):
    monkeypatch.setenv("TEST_REQ", "")
    with pytest.raises(ConfigurationError, match="Missing required"):
        _required_env("TEST_REQ")


def test_required_env_whitespace_only_raises(monkeypatch):
    monkeypatch.setenv("TEST_REQ", "   ")
    with pytest.raises(ConfigurationError, match="Missing required"):
        _required_env("TEST_REQ")


def test_required_env_missing_raises(monkeypatch):
    monkeypatch.delenv("TEST_REQ", raising=False)
    with pytest.raises(ConfigurationError, match="Missing required"):
        _required_env("TEST_REQ")


# ---------------------------------------------------------------------------
# 3. _optional_env
# ---------------------------------------------------------------------------


def test_optional_env_with_set_value(monkeypatch):
    monkeypatch.setenv("TEST_OPT", "value")
    assert _optional_env("TEST_OPT") == "value"


def test_optional_env_strips_whitespace(monkeypatch):
    monkeypatch.setenv("TEST_OPT", "  value  ")
    assert _optional_env("TEST_OPT") == "value"


def test_optional_env_empty_string_returns_none(monkeypatch):
    monkeypatch.setenv("TEST_OPT", "")
    assert _optional_env("TEST_OPT") is None


def test_optional_env_whitespace_only_returns_none(monkeypatch):
    monkeypatch.setenv("TEST_OPT", "   ")
    assert _optional_env("TEST_OPT") is None


def test_optional_env_missing_returns_none(monkeypatch):
    monkeypatch.delenv("TEST_OPT", raising=False)
    assert _optional_env("TEST_OPT") is None


# ---------------------------------------------------------------------------
# 4. _int_env
# ---------------------------------------------------------------------------


def test_int_env_valid_int(monkeypatch):
    monkeypatch.setenv("TEST_INT", "42")
    assert _int_env("TEST_INT", 0) == 42


def test_int_env_missing_returns_default(monkeypatch):
    monkeypatch.delenv("TEST_INT", raising=False)
    assert _int_env("TEST_INT", 7) == 7


def test_int_env_empty_returns_default(monkeypatch):
    monkeypatch.setenv("TEST_INT", "")
    assert _int_env("TEST_INT", 7) == 7


def test_int_env_whitespace_only_returns_default(monkeypatch):
    monkeypatch.setenv("TEST_INT", "   ")
    assert _int_env("TEST_INT", 7) == 7


def test_int_env_invalid_raises(monkeypatch):
    monkeypatch.setenv("TEST_INT", "not-a-number")
    with pytest.raises(ConfigurationError, match="must be an integer"):
        _int_env("TEST_INT", 0)


def test_int_env_float_raises(monkeypatch):
    monkeypatch.setenv("TEST_INT", "3.14")
    with pytest.raises(ConfigurationError, match="must be an integer"):
        _int_env("TEST_INT", 0)


# ---------------------------------------------------------------------------
# 5. _float_env
# ---------------------------------------------------------------------------


def test_float_env_valid_float(monkeypatch):
    monkeypatch.setenv("TEST_FLOAT", "3.14")
    assert _float_env("TEST_FLOAT", 0.0) == pytest.approx(3.14)


def test_float_env_valid_integer_string(monkeypatch):
    monkeypatch.setenv("TEST_FLOAT", "5")
    assert _float_env("TEST_FLOAT", 0.0) == 5.0


def test_float_env_missing_returns_default(monkeypatch):
    monkeypatch.delenv("TEST_FLOAT", raising=False)
    assert _float_env("TEST_FLOAT", 2.5) == pytest.approx(2.5)


def test_float_env_empty_returns_default(monkeypatch):
    monkeypatch.setenv("TEST_FLOAT", "")
    assert _float_env("TEST_FLOAT", 2.5) == pytest.approx(2.5)


def test_float_env_whitespace_only_returns_default(monkeypatch):
    monkeypatch.setenv("TEST_FLOAT", "   ")
    assert _float_env("TEST_FLOAT", 2.5) == pytest.approx(2.5)


def test_float_env_invalid_raises(monkeypatch):
    monkeypatch.setenv("TEST_FLOAT", "not-a-float")
    with pytest.raises(ConfigurationError, match="must be a number"):
        _float_env("TEST_FLOAT", 0.0)


# ---------------------------------------------------------------------------
# 6. _parse_allowed_chat_ids
# ---------------------------------------------------------------------------


def test_parse_allowed_chat_ids_none():
    assert _parse_allowed_chat_ids(None) == frozenset()


def test_parse_allowed_chat_ids_empty_string():
    assert _parse_allowed_chat_ids("") == frozenset()


def test_parse_allowed_chat_ids_single_id():
    assert _parse_allowed_chat_ids("123") == frozenset({123})


def test_parse_allowed_chat_ids_multiple_ids():
    assert _parse_allowed_chat_ids("123,456,789") == frozenset({123, 456, 789})


def test_parse_allowed_chat_ids_with_whitespace():
    assert _parse_allowed_chat_ids(" 123 , 456 , 789 ") == frozenset({123, 456, 789})


def test_parse_allowed_chat_ids_trailing_comma():
    assert _parse_allowed_chat_ids("123,") == frozenset({123})


def test_parse_allowed_chat_ids_non_numeric_raises():
    with pytest.raises(ConfigurationError, match="comma-separated list of numeric"):
        _parse_allowed_chat_ids("abc")


def test_parse_allowed_chat_ids_mixed_valid_invalid_raises():
    with pytest.raises(ConfigurationError, match="comma-separated list of numeric"):
        _parse_allowed_chat_ids("123,abc")


def test_parse_allowed_chat_ids_negative_id():
    assert _parse_allowed_chat_ids("-1") == frozenset({-1})


# ---------------------------------------------------------------------------
# 7. _bool_env
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "YES", "on", "ON"])
def test_bool_env_truthy_values(monkeypatch, value):
    monkeypatch.setenv("TEST_BOOL", value)
    assert _bool_env("TEST_BOOL", False) is True


@pytest.mark.parametrize("value", ["false", "FALSE", "False", "0", "no", "NO", "off", "OFF"])
def test_bool_env_falsy_values(monkeypatch, value):
    monkeypatch.setenv("TEST_BOOL", value)
    assert _bool_env("TEST_BOOL", True) is False


def test_bool_env_missing_returns_default_true(monkeypatch):
    monkeypatch.delenv("TEST_BOOL", raising=False)
    assert _bool_env("TEST_BOOL", True) is True


def test_bool_env_missing_returns_default_false(monkeypatch):
    monkeypatch.delenv("TEST_BOOL", raising=False)
    assert _bool_env("TEST_BOOL", False) is False


def test_bool_env_empty_returns_default(monkeypatch):
    monkeypatch.setenv("TEST_BOOL", "")
    assert _bool_env("TEST_BOOL", True) is True


def test_bool_env_whitespace_only_returns_default(monkeypatch):
    monkeypatch.setenv("TEST_BOOL", "   ")
    assert _bool_env("TEST_BOOL", False) is False


def test_bool_env_invalid_raises(monkeypatch):
    monkeypatch.setenv("TEST_BOOL", "maybe")
    with pytest.raises(ConfigurationError, match="must be a boolean"):
        _bool_env("TEST_BOOL", False)


# ---------------------------------------------------------------------------
# 8. _bible_translation_env
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [("nvi", "nvi"), ("acf", "acf"), ("ra", "ra"), ("arc", "arc")])
def test_bible_translation_env_valid(monkeypatch, value, expected):
    monkeypatch.setenv("TEST_BIBLE", value)
    assert _bible_translation_env("TEST_BIBLE", "nvi") == expected


@pytest.mark.parametrize("value", ["NVI", "Nvi", "ACF", "RA", "ARC"])
def test_bible_translation_env_case_insensitive(monkeypatch, value):
    monkeypatch.setenv("TEST_BIBLE", value)
    assert _bible_translation_env("TEST_BIBLE", "nvi") == value.lower()


def test_bible_translation_env_missing_returns_default(monkeypatch):
    monkeypatch.delenv("TEST_BIBLE", raising=False)
    assert _bible_translation_env("TEST_BIBLE", "nvi") == "nvi"


def test_bible_translation_env_empty_returns_default(monkeypatch):
    monkeypatch.setenv("TEST_BIBLE", "")
    assert _bible_translation_env("TEST_BIBLE", "acf") == "acf"


def test_bible_translation_env_whitespace_only_returns_default(monkeypatch):
    monkeypatch.setenv("TEST_BIBLE", "   ")
    assert _bible_translation_env("TEST_BIBLE", "ra") == "ra"


def test_bible_translation_env_invalid_raises(monkeypatch):
    monkeypatch.setenv("TEST_BIBLE", "kjv")
    with pytest.raises(ConfigurationError, match="must be one of"):
        _bible_translation_env("TEST_BIBLE", "nvi")


# ---------------------------------------------------------------------------
# 9. load_settings — basic
# ---------------------------------------------------------------------------


def test_load_settings_with_token_only(monkeypatch):
    """Only TELEGRAM_BOT_TOKEN set → returns Settings with defaults."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    # Clear optional envs to avoid interference from host env
    for var in [
        "ALLOWED_CHAT_IDS",
        "BACKEND_BASE_URL",
        "BACKEND_API_KEY",
        "BACKEND_MODEL",
        "CALDAV_URL",
        "CALDAV_USERNAME",
        "CALDAV_PASSWORD",
        "CALDAV_CALENDAR_NAME",
        "KBPLUS_BASE_URL",
        "KBPLUS_API_TOKEN",
        "KBPLUS_BOARD_ID",
        "KBPLUS_TODO_COLUMN_ID",
        "KBPLUS_DONE_COLUMN_ID",
        "LOG_LEVEL",
        "STT_ENABLED",
        "STT_LANGUAGE",
        "BIBLE_ENABLED",
        "BIBLE_API_TOKEN",
        "BIBLE_TRANSLATION",
    ]:
        monkeypatch.delenv(var, raising=False)

    settings = load_settings()
    assert settings.telegram_bot_token == "test-token"
    assert settings.allowed_chat_ids == frozenset()
    assert settings.backend_enabled is False
    assert settings.caldav_enabled is False
    assert settings.kbplus_enabled is False
    assert settings.bible_configured is False
    assert settings.log_level == logging.INFO
    assert settings.stt_enabled is False
    assert settings.bible_enabled is False


def test_load_settings_without_token_raises(monkeypatch):
    """Missing TELEGRAM_BOT_TOKEN → ConfigurationError."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(ConfigurationError, match="Missing required"):
        load_settings()


# ---------------------------------------------------------------------------
# 10. Settings.backend_enabled
# ---------------------------------------------------------------------------


def test_backend_enabled_all_set():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
        backend_base_url="http://localhost",
        backend_api_key="key",
        backend_model="gpt-4",
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
        log_level=logging.INFO,
    )
    assert s.backend_enabled is True


def test_backend_enabled_missing_url():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
        backend_base_url=None,
        backend_api_key="key",
        backend_model="gpt-4",
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
        log_level=logging.INFO,
    )
    assert s.backend_enabled is False


def test_backend_enabled_missing_api_key():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
        backend_base_url="http://localhost",
        backend_api_key=None,
        backend_model="gpt-4",
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
        log_level=logging.INFO,
    )
    assert s.backend_enabled is False


def test_backend_enabled_missing_model():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
        backend_base_url="http://localhost",
        backend_api_key="key",
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
        log_level=logging.INFO,
    )
    assert s.backend_enabled is False


# ---------------------------------------------------------------------------
# 11. Settings.caldav_enabled
# ---------------------------------------------------------------------------


def test_caldav_enabled_all_set():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
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
        caldav_url="https://caldav.example.com",
        caldav_username="user",
        caldav_password="pass",
        caldav_calendar_name="Personal",
        log_level=logging.INFO,
    )
    assert s.caldav_enabled is True


def test_caldav_enabled_missing_url():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
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
        caldav_username="user",
        caldav_password="pass",
        caldav_calendar_name="Personal",
        log_level=logging.INFO,
    )
    assert s.caldav_enabled is False


def test_caldav_enabled_missing_username():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
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
        caldav_url="https://caldav.example.com",
        caldav_username=None,
        caldav_password="pass",
        caldav_calendar_name="Personal",
        log_level=logging.INFO,
    )
    assert s.caldav_enabled is False


def test_caldav_enabled_missing_password():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
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
        caldav_url="https://caldav.example.com",
        caldav_username="user",
        caldav_password=None,
        caldav_calendar_name="Personal",
        log_level=logging.INFO,
    )
    assert s.caldav_enabled is False


# ---------------------------------------------------------------------------
# 12. Settings.kbplus_enabled
# ---------------------------------------------------------------------------


def _make_kbplus_settings(**overrides) -> Settings:
    """Build a Settings with all kbplus fields set, allow overrides."""
    defaults = dict(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
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
        log_level=logging.INFO,
        kbplus_base_url="https://kb.example.com",
        kbplus_api_token="token",
        kbplus_board_id="board1",
        kbplus_todo_column_id="todo1",
        kbplus_done_column_id="done1",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_kbplus_enabled_all_set():
    assert _make_kbplus_settings().kbplus_enabled is True


def test_kbplus_enabled_missing_base_url():
    assert _make_kbplus_settings(kbplus_base_url=None).kbplus_enabled is False


def test_kbplus_enabled_missing_api_token():
    assert _make_kbplus_settings(kbplus_api_token=None).kbplus_enabled is False


def test_kbplus_enabled_missing_board_id():
    assert _make_kbplus_settings(kbplus_board_id=None).kbplus_enabled is False


def test_kbplus_enabled_missing_todo_column_id():
    assert _make_kbplus_settings(kbplus_todo_column_id=None).kbplus_enabled is False


def test_kbplus_enabled_missing_done_column_id():
    assert _make_kbplus_settings(kbplus_done_column_id=None).kbplus_enabled is False


# ---------------------------------------------------------------------------
# 13. Settings.bible_configured
# ---------------------------------------------------------------------------


def test_bible_configured_enabled_with_url_and_translation():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
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
        log_level=logging.INFO,
        bible_enabled=True,
        bible_api_base_url="https://bible.api",
        bible_translation="nvi",
    )
    assert s.bible_configured is True


def test_bible_configured_disabled():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
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
        log_level=logging.INFO,
        bible_enabled=False,
        bible_api_base_url="https://bible.api",
        bible_translation="nvi",
    )
    assert s.bible_configured is False


def test_bible_configured_enabled_but_empty_base_url():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
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
        log_level=logging.INFO,
        bible_enabled=True,
        bible_api_base_url="",
        bible_translation="nvi",
    )
    assert s.bible_configured is False


def test_bible_configured_enabled_but_empty_translation():
    s = Settings(
        telegram_bot_token="t",
        allowed_chat_ids=frozenset(),
        database_path="/tmp/db.sqlite3",
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
        log_level=logging.INFO,
        bible_enabled=True,
        bible_api_base_url="https://bible.api",
        bible_translation="",
    )
    assert s.bible_configured is False


# ---------------------------------------------------------------------------
# 14. load_settings LOG_LEVEL
# ---------------------------------------------------------------------------


def test_load_settings_log_level_debug(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    # Clear optional vars that may be set in host env
    for var in [
        "ALLOWED_CHAT_IDS",
        "BACKEND_BASE_URL",
        "BACKEND_API_KEY",
        "BACKEND_MODEL",
        "CALDAV_URL",
        "CALDAV_USERNAME",
        "CALDAV_PASSWORD",
        "CALDAV_CALENDAR_NAME",
        "KBPLUS_BASE_URL",
        "KBPLUS_API_TOKEN",
        "KBPLUS_BOARD_ID",
        "KBPLUS_TODO_COLUMN_ID",
        "KBPLUS_DONE_COLUMN_ID",
        "STT_ENABLED",
        "STT_LANGUAGE",
        "BIBLE_ENABLED",
        "BIBLE_API_TOKEN",
        "BIBLE_TRANSLATION",
    ]:
        monkeypatch.delenv(var, raising=False)
    settings = load_settings()
    assert settings.log_level == logging.DEBUG


def test_load_settings_log_level_invalid_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("LOG_LEVEL", "INVALID")
    with pytest.raises(ConfigurationError, match="LOG_LEVEL"):
        load_settings()


def test_load_settings_log_level_lowercase_valid(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("LOG_LEVEL", "warning")
    for var in [
        "ALLOWED_CHAT_IDS",
        "BACKEND_BASE_URL",
        "BACKEND_API_KEY",
        "BACKEND_MODEL",
        "CALDAV_URL",
        "CALDAV_USERNAME",
        "CALDAV_PASSWORD",
        "CALDAV_CALENDAR_NAME",
        "KBPLUS_BASE_URL",
        "KBPLUS_API_TOKEN",
        "KBPLUS_BOARD_ID",
        "KBPLUS_TODO_COLUMN_ID",
        "KBPLUS_DONE_COLUMN_ID",
        "STT_ENABLED",
        "STT_LANGUAGE",
        "BIBLE_ENABLED",
        "BIBLE_API_TOKEN",
        "BIBLE_TRANSLATION",
    ]:
        monkeypatch.delenv(var, raising=False)
    settings = load_settings()
    assert settings.log_level == logging.WARNING


# ---------------------------------------------------------------------------
# Additional edge cases for load_settings
# ---------------------------------------------------------------------------


def test_load_settings_with_allowed_chat_ids(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "111,222,333")
    for var in [
        "BACKEND_BASE_URL",
        "BACKEND_API_KEY",
        "BACKEND_MODEL",
        "CALDAV_URL",
        "CALDAV_USERNAME",
        "CALDAV_PASSWORD",
        "CALDAV_CALENDAR_NAME",
        "KBPLUS_BASE_URL",
        "KBPLUS_API_TOKEN",
        "KBPLUS_BOARD_ID",
        "KBPLUS_TODO_COLUMN_ID",
        "KBPLUS_DONE_COLUMN_ID",
        "LOG_LEVEL",
        "STT_ENABLED",
        "STT_LANGUAGE",
        "BIBLE_ENABLED",
        "BIBLE_API_TOKEN",
        "BIBLE_TRANSLATION",
    ]:
        monkeypatch.delenv(var, raising=False)
    settings = load_settings()
    assert settings.allowed_chat_ids == frozenset({111, 222, 333})


def test_load_settings_backend_enabled_via_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("BACKEND_BASE_URL", "http://ai.local")
    monkeypatch.setenv("BACKEND_API_KEY", "key123")
    monkeypatch.setenv("BACKEND_MODEL", "llama3")
    for var in [
        "ALLOWED_CHAT_IDS",
        "CALDAV_URL",
        "CALDAV_USERNAME",
        "CALDAV_PASSWORD",
        "CALDAV_CALENDAR_NAME",
        "KBPLUS_BASE_URL",
        "KBPLUS_API_TOKEN",
        "KBPLUS_BOARD_ID",
        "KBPLUS_TODO_COLUMN_ID",
        "KBPLUS_DONE_COLUMN_ID",
        "LOG_LEVEL",
        "STT_ENABLED",
        "STT_LANGUAGE",
        "BIBLE_ENABLED",
        "BIBLE_API_TOKEN",
        "BIBLE_TRANSLATION",
    ]:
        monkeypatch.delenv(var, raising=False)
    settings = load_settings()
    assert settings.backend_enabled is True
