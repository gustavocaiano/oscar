"""Error classification for AI backend (cliproxy) HTTP failures.

Maps HTTP status codes and response bodies to clear, actionable error messages
with remediation hints for the admin/operator.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


def classify_http_error(
    status_code: int,
    response_body: str | None = None,
) -> tuple[str, int | None, str | None]:
    """Map an HTTP error status code + response body to a clear, actionable message.

    Returns:
        A tuple of (message, status_code, detail) where:
        - message: human-friendly error text with remediation hints
        - status_code: the original HTTP status code (for AIBackendError)
        - detail: extracted error detail from the response body (for AIBackendError)
    """
    detail = _extract_error_detail(response_body)

    if status_code == 400:
        msg = "Bad request to AI backend"
        hint = "The model name may be invalid or the request format is unsupported."
        action = "Check BACKEND_MODEL in .env and run: docker logs cliproxyapi --tail 50"
    elif status_code == 401:
        msg = "AI backend authentication failed"
        hint = "The API key was rejected."
        action = "Check BACKEND_API_KEY in .env matches cliproxy config. Run: docker logs cliproxyapi --tail 50"
    elif status_code == 403:
        msg = "AI backend access denied"
        hint = "Permission or quota issue."
        action = "Check cliproxy API key permissions and quota. Run: docker logs cliproxyapi --tail 50"
    elif status_code == 429:
        msg = "AI backend rate limit exceeded"
        hint = "Too many requests. Wait a moment and try again."
        action = "If persistent, check quota: docker logs cliproxyapi --tail 200 | grep -i quota"
    elif status_code in (500, 502, 503):
        msg = "AI backend server error"
        hint = "The cliproxy service may be misconfigured or the upstream provider is down."
        action = "Try: docker restart cliproxyapi && docker logs cliproxyapi --tail 50"
    else:
        msg = f"AI backend returned HTTP {status_code}"
        hint = None
        action = "Run: docker logs cliproxyapi --tail 50"

    parts: list[str] = [msg]
    if hint:
        parts.append(hint)
    if detail:
        parts.append(f"Detail: {detail}")
    if action:
        parts.append(f"→ {action}")

    return "\n".join(parts), status_code, detail


def classify_connection_error(error: httpx.HTTPError) -> tuple[str, int | None, str | None]:
    """Classify connection/transport errors (not HTTP status errors).

    Returns:
        A tuple of (message, status_code, detail) suitable for AIBackendError.
    """
    error_str = str(error).lower()
    if "connectionrefused" in error_str or "connection refused" in error_str:
        message = (
            "Cannot reach AI backend (cliproxyapi).\n"
            "The cliproxy service may not be running.\n"
            "→ Check: docker ps | grep cliproxyapi\n"
            "→ Start: docker compose up -d cliproxyapi"
        )
    elif "connecttimeout" in error_str or "timed out" in error_str:
        message = (
            "AI backend connection timed out.\n"
            "The cliproxy service may be overloaded or unresponsive.\n"
            "→ Check: docker logs cliproxyapi --tail 50"
        )
    else:
        message = (
            f"AI backend connection failed: {type(error).__name__}\n"
            "→ Check: docker ps | grep cliproxyapi && docker logs cliproxyapi --tail 50"
        )
    return message, None, None


def classify_timeout_error() -> tuple[str, int | None, str | None]:
    """Classify a timeout error (request sent but no response in time).

    Returns:
        A tuple of (message, status_code, detail) suitable for AIBackendError.
    """
    message = (
        "AI backend timed out.\n"
        "The request took too long. The model or provider may be slow.\n"
        "→ Try again, or check: docker logs cliproxyapi --tail 50"
    )
    return message, None, None


def _extract_error_detail(body: str | None) -> str | None:
    """Try to extract the error message from an OpenAI-style JSON response body.

    Handles:
    - OpenAI-style: {"error": {"message": "...", "type": "...", "code": "..."}}
    - Simple string: {"error": "..."}
    - Raw text fallback (first 200 chars)
    """
    if not body:
        return None
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                return error.get("message") or error.get("code")
            if isinstance(error, str):
                return error
    except (json.JSONDecodeError, AttributeError):
        return body[:200].strip() if body.strip() else None
    return None
