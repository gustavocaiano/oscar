# Oscar — Agent Instructions

Telegram personal assistant bot. Python 3.12, single package under `src/personal_assistant_bot/`.

## Commands

```bash
# Install (editable with dev deps)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Required once after install — Playwright chromium for web search tool
python -m playwright install chromium

# Lint → format → typecheck → test (run in this order)
ruff check .
ruff format --check .
mypy src/          # non-blocking: CI uses continue-on-error, tighten incrementally
pytest --tb=short -q

# Additional static check
python3 -m compileall src

# Docker compose config validation (needs .env.example)
docker compose --env-file .env.example config
```

## Package layout

- Source: `src/personal_assistant_bot/` — setuptools `packages.find(where=["src"])`
- Entry point: `personal_assistant_bot.main:main` (also `python -m personal_assistant_bot.main`)
- Tests: `tests/` flat, no conftest fixtures — each test file builds `Settings` + `SQLiteStorage` with temp paths and fake service stubs

## Toolchain specifics

- **Ruff**: target py312, line-length 120, double quotes. Rules: E, W, F, I, UP, B, SIM, RUF100. E501 ignored (formatter handles it). Tests allow B011 (`assert False`).
- **MyPy**: permissive by design (`disallow_untyped_defs=false`, `disallow_incomplete_defs=false`). Missing imports ignored for: `faster_whisper`, `caldav`, `icalendar`, `telegram`, `playwright`.
- **Pytest**: `testpaths = ["tests"]` in pyproject.toml. CI installs Playwright chromium with `--with-deps` before running tests.

## Architecture

- **Config**: all env-var driven via `config.py` → frozen `Settings` dataclass. Only `TELEGRAM_BOT_TOKEN` is required. Optional groups: `BACKEND_*` (AI), `CALDAV_*` (calendar), `KBPLUS_*` (task backend), `STT_*` (speech-to-text). Each group activates only when all its vars are set.
- **Storage**: SQLite via `storage.py`. Path defaults to `/data/assistant.sqlite3` (Docker) or env override.
- **Integrations** deactivate gracefully — missing CalDAV or KB+ just disables those commands with a clear message.
- **AI writes** are approval-gated: the bot proposes actions, user confirms via inline buttons or `/confirm`/`/reject` tokens.
- **Voice notes**: local-only via `faster-whisper`. No system `ffmpeg` needed (uses PyAV). Single concurrent transcription to protect CPU.

## CI / Deploy

- **CI** (on all pushes, PRs to main): lint → test (with Playwright) → typecheck (non-blocking) → Docker build + compose config check.
- **Deploy** (push to main or `v*` tags): CI → build Docker image → push to `ghcr.io/gustavocaiano/oscar` → SSH deploy to `/opt/oscar` (pull + recreate assistant container).
- **Docker image**: `python:3.12-slim`, installs Playwright chromium at build time. Compose stack: `assistant` (3.5GB limit) + `cliproxyapi` (512MB limit).
