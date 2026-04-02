# Telegram Personal Assistant

Telegram-first personal assistant in Python with:

- tasks and shopping lists
- notes/inbox capture
- reminders
- iCloud Calendar integration through CalDAV
- hour tracking inspired by `hcounter`
- AI chat for normal messages
- approval flow before AI-originated writes
- proactive morning briefs, reminder alerts, hour reminders, and evening wrap-ups
- optional local speech-to-text for Telegram voice notes

## Command style

Telegram bot commands do **not** support `-` or `.` in command names.

Because of that, this assistant uses **root commands with subcommands**:

- `/task add ...`
- `/shop add ...`
- `/cal list ...`
- `/h add ...`

This keeps the grouped namespace feel you wanted while staying Telegram-compatible.

## Features

### Structured commands

- `/task add <text>`
- `/task list`
- `/task done <id>`
- `/task rename <id> | <new title>`

- `/shop add eggs, bread`
- `/shop list`
- `/shop buy <id>`
- `/shop rename <id> | <new title>`

- `/note add <text>`
- `/note inbox <text>`
- `/note list [count]`
- `/note search <query>`

- `/rem add YYYY-MM-DD HH:MM | message`
- `/rem list`
- `/rem done <id>`
- `/rem cancel <id>`

- `/cal list [days]`
- `/cal add YYYY-MM-DD HH:MM | YYYY-MM-DD HH:MM | title [| description]`

- `/h add 2h 30m`
- `/h month [MM]`

- `/pref show`
- `/pref enable <morning|hours|evening|reminders>`
- `/pref disable <...>`
- `/pref time <morning|hours|evening> HH:MM`
- `/pref timezone <Area/Location>`

- `/confirm <token>`
- `/reject <token>`

AI approvals now use **inline Confirm / Deny buttons** by default. The slash commands remain as fallback.

### AI mode

If you send a normal message without a slash command:

- the assistant uses the configured OpenAI-compatible backend
- it can read your tasks, shopping items, reminders, notes, hours, and agenda
- if it wants to write data, it proposes an action and asks you to confirm it first
- it can now propose multiple themed tool actions in one turn and bundle them into one confirmation request

Supported AI-originated write proposals are grouped by theme in the current implementation:

- tasks
- shopping
- notes
- reminders
- calendar

Examples of what the AI can now propose in one request:

- create multiple tasks
- add multiple shopping items
- create a reminder plus a calendar event
- rename or complete an existing task/shopping item

### Voice notes

If local speech-to-text is enabled, you can send a **Telegram voice note** and the bot will:

- download it temporarily on the server
- transcribe it locally with `faster-whisper`
- show you the recognized transcript
- run the transcript through the same normal AI-chat flow

Current scope:

- Telegram **voice notes only**
- normal `audio` files are not supported yet
- strict size/duration limits are recommended for small CPU-only servers

## Environment variables

Copy the template first:

```bash
cp .env.example .env
```

Main variables:

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | Telegram bot token from BotFather |
| `ALLOWED_CHAT_IDS` | no | Optional comma-separated allowlist of Telegram chat ids |
| `DATABASE_PATH` | no | SQLite database path |
| `BACKEND_BASE_URL` | for AI | OpenAI-compatible backend base URL |
| `BACKEND_API_KEY` | for AI | Backend API key |
| `BACKEND_MODEL` | for AI | Model name |
| `BACKEND_TIMEOUT_SECONDS` | no | AI request timeout |
| `CHAT_HISTORY_LIMIT` | no | Number of stored chat turns sent to AI |
| `APPROVAL_TTL_MINUTES` | no | Expiry time for `/confirm` / `/reject` tokens |
| `DEFAULT_TIMEZONE` | no | Default timezone for new chats |
| `MORNING_BRIEF_TIME` | no | Default morning briefing time |
| `HOUR_REMINDER_TIME` | no | Default daily hour reminder time |
| `EVENING_WRAP_UP_TIME` | no | Default evening wrap-up time |
| `REMINDER_SCAN_SECONDS` | no | Poll interval for due reminders and daily schedules |
| `CALDAV_URL` | for calendar | iCloud/CalDAV server URL |
| `CALDAV_USERNAME` | for calendar | CalDAV username |
| `CALDAV_PASSWORD` | for calendar | App-specific password recommended |
| `CALDAV_CALENDAR_NAME` | no | Preferred calendar name |
| `KBPLUS_BASE_URL` | no | KB+ base URL for the task backend |
| `KBPLUS_API_TOKEN` | no | KB+ external integration bearer token |
| `KBPLUS_BOARD_ID` | no | KB+ board id Oscar uses as the task source of truth |
| `KBPLUS_TODO_COLUMN_ID` | no | KB+ column id where Oscar creates new tasks |
| `KBPLUS_DONE_COLUMN_ID` | no | KB+ column id Oscar uses when completing tasks |
| `KBPLUS_TIMEOUT_SECONDS` | no | KB+ request timeout |
| `STT_ENABLED` | no | Enable local speech-to-text for Telegram voice notes |
| `STT_MODEL` | no | Whisper model name, default `base` |
| `STT_DEVICE` | no | Inference device, default `cpu` |
| `STT_COMPUTE_TYPE` | no | Compute type, default `int8` |
| `STT_LANGUAGE` | no | Optional fixed language code; leave empty for auto-detect |
| `STT_VAD_FILTER` | no | Enable VAD filtering, default `true` |
| `STT_MAX_DURATION_SECONDS` | no | Max supported voice-note duration, default `60` |
| `STT_MAX_FILE_SIZE_MB` | no | Max supported voice-note size, default `10` |
| `STT_MODEL_DIR` | no | Model cache directory, default `/models/whisper` |
| `STT_ECHO_TRANSCRIPT` | no | Show recognized transcript back to the user, default `true` |

## iCloud / CalDAV setup

If you use iCloud Calendar, use an **app-specific password**.

Typical setup values:

- `CALDAV_URL=https://caldav.icloud.com`
- `CALDAV_USERNAME=<your Apple ID email>`
- `CALDAV_PASSWORD=<app-specific password>`
- `CALDAV_CALENDAR_NAME=<optional exact calendar name>`

If CalDAV is not configured, the rest of the assistant still works and calendar commands return a clear message.

The briefing/calendar snapshot now distinguishes between:

- no upcoming events
- calendar integration unavailable
- calendar read errors such as missing/mismatched calendar names

## KB+ task backend

Oscar can optionally use KB+ as the **task source of truth** when the KB+ integration variables are configured.

Current Oscar-side behavior:

- KB+ becomes the task backend for `/task ...` commands and AI task actions
- `/task list` groups non-done tasks by KB+ column name
- new tasks are created in `KBPLUS_TODO_COLUMN_ID`
- `/task done ...` moves the task into `KBPLUS_DONE_COLUMN_ID`
- all other KB+ columns are treated as non-done/open columns for listing purposes
- Oscar local storage remains the source of truth for shopping items, reminders, notes, hours, and chat history
- KB+ integration is inactive unless all KB+ environment variables are set

The corresponding KB+ server-side integration endpoints and token UI are described in `kbplus-changes.md`.

## AI backend setup

The bot expects an **OpenAI-compatible** chat completions endpoint.

Example with CLIProxyAPI + Codex-style flow:

1. Copy the example config:

   ```bash
   mkdir -p deploy/cliproxyapi data/cliproxy-auth data/cliproxy-logs data
   cp deploy/cliproxyapi/config.example.yaml deploy/cliproxyapi/config.yaml
   ```

2. Set the same client key in:

   - `.env` → `BACKEND_API_KEY`
   - `deploy/cliproxyapi/config.yaml` → `api-keys`

3. Authenticate CLIProxyAPI with Codex/OpenAI OAuth:

   ```bash
   docker compose run --rm --service-ports cliproxyapi /CLIProxyAPI/CLIProxyAPI --codex-login
   ```

4. Start the stack:

   ```bash
   docker compose up -d
   ```

If you use another backend, just point `BACKEND_BASE_URL`, `BACKEND_API_KEY`, and `BACKEND_MODEL` to it.

## Local speech-to-text setup

The bot can transcribe Telegram **voice notes** locally on the server.

Recommended defaults for your current target shape:

- CPU only
- `STT_MODEL=base`
- `STT_DEVICE=cpu`
- `STT_COMPUTE_TYPE=int8`
- `STT_MAX_DURATION_SECONDS=60`

Example:

```env
STT_ENABLED=true
STT_MODEL=base
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
STT_LANGUAGE=
STT_VAD_FILTER=true
STT_MAX_DURATION_SECONDS=60
STT_MAX_FILE_SIZE_MB=10
STT_MODEL_DIR=/models/whisper
STT_ECHO_TRANSCRIPT=true
```

Notes:

- this implementation uses `faster-whisper`
- `faster-whisper` uses PyAV, so a system `ffmpeg` binary is **not required** for the initial voice-note flow
- the Docker Compose file mounts a persistent model cache at `./data/whisper-models:/models/whisper`
- only one transcription is processed at a time to protect small CPU-only servers

## Local development

Install locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Run:

```bash
python -m personal_assistant_bot.main
```

## Validation

Static/smoke checks:

```bash
python3 -m compileall src
python3 -m pytest
docker compose --env-file .env.example config
```

## Manual end-to-end checklist

1. Fill `.env` with your Telegram token and AI backend settings.
2. If using CalDAV, set the calendar credentials.
3. Start the bot.
4. In Telegram:
   - `/start`
   - `/task add Renew passport`
   - `/shop add eggs, coffee`
   - `/note inbox call landlord`
   - `/rem add 2026-04-01 09:00 | Call the bank`
   - `/h add 2h 30m`
   - `/cal list 7`
5. Send a normal message like:

   ```
   what do i have to do today and what do i need to buy?
   ```

6. Try an AI-originated write request such as:

   ```
   add buy cat food to my shopping list
   ```

7. Confirm the proposed action with the inline button, or fallback to `/confirm <token>`.
8. If speech-to-text is enabled, send a short Portuguese or English voice note and confirm the transcript is shown before the assistant reply.

## Notes

- The bot stores assistant-managed data in SQLite.
- Calendar remains optional.
- AI writes are approval-gated by design.
- The current AI action set is intentionally limited and non-agentic.
- Voice-note transcription is local-first, CPU-oriented, and intentionally limited to short voice notes in the initial release.
