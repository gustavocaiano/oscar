# Better AI Backend Error Messages

## Problem

When cliproxy inference fails, the Telegram bot shows raw httpx error strings like:

> `The AI backend request failed: 400 Bad Request for url: http://cliproxyapi:8317/api/provider/openai/v1/chat/completions`

This is unhelpful because:
1. **No error classification** — 400 (bad request), 401 (auth), 429 (rate limit), 500 (server error) all produce the same generic pattern
2. **No actionable guidance** — the user has no idea what to do to fix it
3. **Internal URL leaked** — `http://cliproxyapi:8317/...` is an internal Docker URL, irrelevant to the user
4. **Response body discarded** — cliproxy likely returns `{"error": {"message": "..."}}` in the JSON body with specific error details, but `raise_for_status()` throws before the body is read

## Scope

- **In scope**: AI backend (cliproxy) error messages only — the most common and confusing failure path
- **Out of scope**: KB+, Calendar, Speech-to-Text errors; retry logic; other integrations

## User

The sole user is also the admin, so remediation hints can include server-side commands (docker, logs, config).

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Retry transient errors? | No | Cliproxy already has `request-retry: 3` internally; just improve messages |
| Response body extraction? | Yes | Read JSON body before raising; include cliproxy's error message |
| Error classification approach | Improve `AIBackendError` messages with status-code mapping | Keep it simple; one class, better messages |
| URL sanitization? | Yes | Strip internal Docker URLs from user-facing output |
| Remediation commands in messages? | Yes | Admin is the only user; actionable hints are valuable |

## Implementation Plan

### Step 1: Create error classification module

**New file**: `src/personal_assistant_bot/ai_errors.py`

Define an error classification function that maps HTTP status codes + response body to clear, actionable messages:

```python
class AIBackendError(RuntimeError):
    """Raised when the AI backend (cliproxy) request fails."""

    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail  # cliproxy response body error message


def classify_http_error(
    status_code: int,
    response_body: str | None = None,
    method: str = "POST",
    url: str = "",
) -> AIBackendError:
    """Map an HTTP error status code + response body to a clear AIBackendError."""

    # Try to extract OpenAI-style error message from body
    detail = _extract_error_detail(response_body)

    # Map status codes to user-friendly messages with remediation hints
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

    parts = [msg]
    if hint:
        parts.append(hint)
    if detail:
        parts.append(f"Detail: {detail}")
    if action:
        parts.append(f"→ {action}")

    return AIBackendError("\n".join(parts), status_code=status_code, detail=detail)


def classify_connection_error(error: httpx.HTTPError) -> AIBackendError:
    """Classify connection/transport errors (not HTTP status errors)."""

    error_str = str(error).lower()
    if "connectionrefused" in error_str or "connection refused" in error_str:
        return AIBackendError(
            "Cannot reach AI backend (cliproxyapi).\n"
            "The cliproxy service may not be running.\n"
            "→ Check: docker ps | grep cliproxyapi\n"
            "→ Start: docker compose up -d cliproxyapi",
            status_code=None,
            detail=None,
        )
    if "connecttimeout" in error_str or "timed out" in error_str:
        return AIBackendError(
            "AI backend connection timed out.\n"
            "The cliproxy service may be overloaded or unresponsive.\n"
            "→ Check: docker logs cliproxyapi --tail 50",
            status_code=None,
            detail=None,
        )
    # Generic connection error
    return AIBackendError(
        f"AI backend connection failed: {type(error).__name__}\n"
        "→ Check: docker ps | grep cliproxyapi && docker logs cliproxyapi --tail 50",
        status_code=None,
        detail=None,
    )


def _extract_error_detail(body: str | None) -> str | None:
    """Try to extract the error message from an OpenAI-style JSON response body."""
    if not body:
        return None
    try:
        data = json.loads(body)
        # OpenAI-style: {"error": {"message": "...", "type": "...", "code": "..."}}
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                return error.get("message") or error.get("code")
            if isinstance(error, str):
                return error
    except (json.JSONDecodeError, AttributeError):
        # Not JSON — try to use first 200 chars of body
        return body[:200].strip() if body.strip() else None
    return None
```

### Step 2: Refactor `ai.py` error handling

**File**: `src/personal_assistant_bot/ai.py`

**Changes**:

1. **Import** the new `classify_http_error`, `classify_connection_error` from `ai_errors`
2. **Replace `raise_for_status()` + broad `except httpx.HTTPError`** with explicit status code checking and body extraction:

**Before** (lines ~239-280):
```python
try:
    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
        # ... loop ...
except httpx.TimeoutException as exc:
    raise AIBackendError("The AI backend timed out") from exc
except httpx.HTTPError as exc:
    raise AIBackendError(f"The AI backend request failed: {exc}") from exc
```

**After**:
```python
try:
    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
        # ... loop ...
except httpx.TimeoutException:
    raise AIBackendError(
        "AI backend timed out.\n"
        "The request took too long. The model or provider may be slow.\n"
        "→ Try again, or check: docker logs cliproxyapi --tail 50",
        status_code=None,
        detail=None,
    )
except httpx.HTTPStatusError as exc:
    # Extract response body before it's lost
    body = None
    try:
        body = exc.response.text
    except Exception:
        pass
    raise classify_http_error(
        status_code=exc.response.status_code,
        response_body=body,
    ) from exc
except httpx.HTTPError as exc:
    # Connection errors, transport errors (not status-code errors)
    raise classify_connection_error(exc) from exc
```

3. **Replace `response.raise_for_status()`** calls (lines ~302, ~341) with explicit status checking:

**Before** (line ~302):
```python
response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
response.raise_for_status()
```

**After**:
```python
response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
if response.is_error:
    raise classify_http_error(
        status_code=response.status_code,
        response_body=response.text,
    )
```

Same pattern for the streaming call site (line ~341).

### Step 3: Update `bot.py` error display (minor)

**File**: `src/personal_assistant_bot/bot.py`

The `AIBackendError` message already flows through to Telegram via `str(exc)` at line 564. Since we're improving the message content in `ai.py`, the Telegram output will automatically be better.

**Optional enhancement**: Add Telegram formatting (monospace for commands):

```python
except AIBackendError as exc:
    logger.warning("AI backend failure: %s", exc)
    # Format remediation hints with code blocks for readability
    formatted = _format_error_for_telegram(str(exc))
    await message.reply_text(self._prepend_transcript_feedback(formatted, transcript_feedback))
    return
```

Where `_format_error_for_telegram` wraps `→ ...` lines in backticks for monospace rendering.

**Decision**: This is a minor polish step. The core value is in Steps 1-2. This step can be deferred.

### Step 4: Add tests for error classification

**File**: `tests/test_ai_errors.py` (new)

Test cases:
- `classify_http_error(400, '{"error": {"message": "Model not found"}}')` → contains "Bad request" + "Model not found" + remediation hint
- `classify_http_error(401, None)` → contains "authentication failed" + API key hint
- `classify_http_error(429, None)` → contains "rate limit"
- `classify_http_error(500, None)` → contains "server error" + docker restart hint
- `classify_http_error(418, None)` → contains "HTTP 418" (fallback)
- `classify_connection_error(ConnectError(...))` → contains "Cannot reach"
- `classify_connection_error(TimeoutException(...))` → contains "timed out"
- `_extract_error_detail` with valid JSON, invalid JSON, None, empty string
- `AIBackendError` attributes (status_code, detail)

## Files Changed

| File | Change |
|------|--------|
| `src/personal_assistant_bot/ai_errors.py` | **New** — Error classification module |
| `src/personal_assistant_bot/ai.py` | **Modify** — Replace `raise_for_status()` + broad catch with classified errors |
| `src/personal_assistant_bot/bot.py` | **Minor** — Import `AIBackendError` from new location (or re-export from `ai_errors`) |
| `tests/test_ai_errors.py` | **New** — Tests for error classification |

## Example: Before vs After

### Before (current)
```
The AI backend request failed: 400 Bad Request for url: http://cliproxyapi:8317/api/provider/openai/v1/chat/completions
```

### After
```
Bad request to AI backend
The model name may be invalid or the request format is unsupported.
Detail: Model 'gpt-5.4' not found
→ Check BACKEND_MODEL in .env and run: docker logs cliproxyapi --tail 50
```

### Before (current)
```
The AI backend request failed: 500 Internal Server Error for url: http://cliproxyapi:8317/api/provider/openai/v1/chat/completions
```

### After
```
AI backend server error
The cliproxy service may be misconfigured or the upstream provider is down.
→ Try: docker restart cliproxyapi && docker logs cliproxyapi --tail 50
```

### Before (current)
```
The AI backend request failed: Connection refused
```

### After
```
Cannot reach AI backend (cliproxyapi).
The cliproxy service may not be running.
→ Check: docker ps | grep cliproxyapi
→ Start: docker compose up -d cliproxyapi
```

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| cliproxy response body format is unknown (no public docs) | `_extract_error_detail` handles multiple formats: OpenAI-style JSON `{"error": {"message": "..."}}`, plain string `{"error": "..."}`, raw text fallback |
| `response.text` may not be available on streaming errors | Wrap in try/except; fall back to no detail |
| Moving `AIBackendError` to a new module breaks imports | Keep `AIBackendError` in `ai.py` initially, import classification functions from `ai_errors.py` |
| Overly verbose Telegram messages | Error messages are ~3 lines; acceptable for admin-user scenario |

## Open / Deferred Items

- **Telegram formatting** (monospace for commands) — optional polish, can be added later
- **Retry logic for transient errors** — out of scope per user decision; cliproxy handles retries internally
- **Other integration error messages** (KB+, Calendar, Speech) — out of scope for this change
- **Structured logging** — the `logger.warning` in bot.py already logs the error; could add `exc.detail` as structured data later
- **Docker healthcheck for cliproxyapi** — could prevent some "connection refused" errors but out of scope
