"""Tests for AI backend error classification."""

from __future__ import annotations

import httpx

from personal_assistant_bot.ai import AIBackendError
from personal_assistant_bot.ai_errors import (
    _extract_error_detail,
    classify_connection_error,
    classify_http_error,
    classify_timeout_error,
)

# --- classify_http_error ---


class TestClassifyHttpError:
    def test_400_with_openai_error_body(self) -> None:
        body = '{"error": {"message": "Model not found", "type": "invalid_request_error", "code": "model_not_found"}}'
        message, status_code, detail = classify_http_error(400, body)
        assert status_code == 400
        assert detail == "Model not found"
        assert "Bad request" in message
        assert "model name" in message.lower()
        assert "Model not found" in message
        assert "docker logs" in message

    def test_400_without_body(self) -> None:
        message, status_code, detail = classify_http_error(400, None)
        assert status_code == 400
        assert detail is None
        assert "Bad request" in message
        assert "model name" in message.lower()
        assert "docker logs" in message

    def test_401_auth_failed(self) -> None:
        message, status_code, detail = classify_http_error(401, None)
        assert status_code == 401
        assert "authentication failed" in message.lower()
        assert "API key" in message
        assert "BACKEND_API_KEY" in message

    def test_403_access_denied(self) -> None:
        message, status_code, detail = classify_http_error(403, None)
        assert status_code == 403
        assert "access denied" in message.lower()
        assert "quota" in message.lower()

    def test_429_rate_limit(self) -> None:
        message, status_code, detail = classify_http_error(429, None)
        assert status_code == 429
        assert "rate limit" in message.lower()
        assert "wait" in message.lower()
        assert "quota" in message.lower()

    def test_500_server_error(self) -> None:
        message, status_code, detail = classify_http_error(500, None)
        assert status_code == 500
        assert "server error" in message.lower()
        assert "docker restart" in message

    def test_502_server_error(self) -> None:
        message, status_code, detail = classify_http_error(502, None)
        assert status_code == 502
        assert "server error" in message.lower()

    def test_503_server_error(self) -> None:
        message, status_code, detail = classify_http_error(503, None)
        assert status_code == 503
        assert "server error" in message.lower()

    def test_unknown_status_code_fallback(self) -> None:
        message, status_code, detail = classify_http_error(418, None)
        assert status_code == 418
        assert "HTTP 418" in message
        assert "docker logs" in message

    def test_500_with_error_detail_in_body(self) -> None:
        body = '{"error": "Internal server error"}'
        message, status_code, detail = classify_http_error(500, body)
        assert detail == "Internal server error"
        assert "Internal server error" in message

    def test_400_with_plain_string_error_body(self) -> None:
        body = '{"error": "Invalid model specified"}'
        message, status_code, detail = classify_http_error(400, body)
        assert detail == "Invalid model specified"
        assert "Invalid model specified" in message

    def test_action_line_format(self) -> None:
        message, _, _ = classify_http_error(400, None)
        # Every classified error should have an action hint with →
        assert "→" in message


# --- classify_connection_error ---


class TestClassifyConnectionError:
    def test_connection_refused(self) -> None:
        error = httpx.ConnectError("Connection refused")
        message, status_code, detail = classify_connection_error(error)
        assert status_code is None
        assert detail is None
        assert "Cannot reach" in message
        assert "cliproxyapi" in message
        assert "docker ps" in message
        assert "docker compose up" in message

    def test_connect_timeout(self) -> None:
        error = httpx.ConnectTimeout("Timed out")
        message, status_code, detail = classify_connection_error(error)
        assert "timed out" in message.lower()
        assert "docker logs" in message

    def test_generic_http_error(self) -> None:
        error = httpx.WriteError("Write error")
        message, _, _ = classify_connection_error(error)
        assert "connection failed" in message.lower()
        assert "WriteError" in message
        assert "docker ps" in message


# --- classify_timeout_error ---


class TestClassifyTimeoutError:
    def test_timeout_message(self) -> None:
        message, status_code, detail = classify_timeout_error()
        assert status_code is None
        assert detail is None
        assert "timed out" in message.lower()
        assert "docker logs" in message


# --- _extract_error_detail ---


class TestExtractErrorDetail:
    def test_openai_style_nested_error(self) -> None:
        body = '{"error": {"message": "Model not found", "type": "invalid_request_error", "code": "model_not_found"}}'
        assert _extract_error_detail(body) == "Model not found"

    def test_openai_style_code_fallback(self) -> None:
        body = '{"error": {"type": "invalid_request_error", "code": "model_not_found"}}'
        assert _extract_error_detail(body) == "model_not_found"

    def test_string_error(self) -> None:
        body = '{"error": "Something went wrong"}'
        assert _extract_error_detail(body) == "Something went wrong"

    def test_none_body(self) -> None:
        assert _extract_error_detail(None) is None

    def test_empty_body(self) -> None:
        assert _extract_error_detail("") is None

    def test_whitespace_body(self) -> None:
        assert _extract_error_detail("   ") is None

    def test_invalid_json_fallback(self) -> None:
        body = "This is not JSON but it is an error message from the server"
        result = _extract_error_detail(body)
        assert result is not None
        assert "This is not JSON" in result

    def test_long_non_json_truncated(self) -> None:
        body = "X" * 500
        result = _extract_error_detail(body)
        assert result is not None
        assert len(result) <= 200

    def test_json_without_error_key(self) -> None:
        body = '{"status": "ok", "data": []}'
        assert _extract_error_detail(body) is None

    def test_error_key_is_number(self) -> None:
        body = '{"error": 42}'
        assert _extract_error_detail(body) is None


# --- AIBackendError attributes ---


class TestAIBackendErrorAttributes:
    def test_default_attributes(self) -> None:
        err = AIBackendError("Something went wrong")
        assert str(err) == "Something went wrong"
        assert err.status_code is None
        assert err.detail is None

    def test_with_status_code_and_detail(self) -> None:
        err = AIBackendError("Bad request", status_code=400, detail="Model not found")
        assert str(err) == "Bad request"
        assert err.status_code == 400
        assert err.detail == "Model not found"

    def test_is_runtime_error(self) -> None:
        err = AIBackendError("test")
        assert isinstance(err, RuntimeError)
