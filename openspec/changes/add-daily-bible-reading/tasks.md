## 1. Configuration and Provider Client

- [x] 1.1 Add Bible settings to `Settings`, including explicit enablement, API base URL, optional token, Portuguese translation, daily time, and timeout.
- [x] 1.2 Update `.env.example` with Bible feature group variables and safe disabled-by-default defaults.
- [x] 1.3 Add Portuguese Bible book metadata for canonical order, ABíbliaDigital abbreviations, and chapter counts.
- [x] 1.4 Implement a Bible provider/client that fetches one full Portuguese chapter from ABíbliaDigital and validates the response shape.
- [x] 1.5 Add provider/client tests for successful chapter parsing, missing token behavior, HTTP failures, and invalid responses.

## 2. Storage and Progress Tracking

- [x] 2.1 Add SQLite schema for `bible_reading_progress` and `bible_daily_prompt_claims` without changing existing scheduled notification constraints.
- [x] 2.2 Add storage dataclasses and CRUD methods for reading progress creation, retrieval, update, completion, and sequential advancement.
- [x] 2.3 Add storage methods for claiming, marking, and releasing a daily Bible prompt per chat/date.
- [x] 2.4 Add storage tests proving first-read defaults to Genesis 1, chapter/book advancement works, completion does not auto-wrap, and prompt claims are unique per date.

## 3. Scheduler Integration

- [x] 3.1 Extend the scheduled notification model or flow to represent a Bible reading prompt with inline keyboard metadata.
- [x] 3.2 Add daily Bible prompt evaluation to the reminder scan loop using each chat's local timezone and configured Bible daily time.
- [x] 3.3 Ensure missed days do not create backlog by checking only the current local date and one prompt claim per chat/date.
- [x] 3.4 Add scheduler tests for due prompt creation, duplicate suppression on the same date, and no catch-up after multiple missed days.

## 4. Telegram Actions and Commands

- [x] 4.1 Add a Portuguese Bible prompt inline keyboard with `Ler capítulo` and `Hoje não` actions.
- [x] 4.2 Add callback routing for Bible actions without interfering with existing approval callbacks.
- [x] 4.3 Implement the read action so it fetches exactly one next chapter, sends it, and advances progress only after successful delivery.
- [x] 4.4 Implement the dismiss action so it edits or acknowledges the prompt without sending a chapter or changing progress.
- [x] 4.5 Add a deterministic `/biblia` command to read the next chapter on demand, plus a minimal status response if no read action is requested.

## 5. Chapter Formatting and AI Resume

- [x] 5.1 Format chapter delivery in Portuguese with book/chapter title and numbered verses from the provider response.
- [x] 5.2 Split long chapter output into ordered Telegram-safe message chunks before marking progress advanced.
- [x] 5.3 Add optional AI backend formatting/resume path with a constrained Portuguese prompt and raw-format fallback on AI errors.
- [x] 5.4 Add tests for raw formatting, long chapter splitting, AI success, and AI fallback behavior.

## 6. End-to-End Validation

- [x] 6.1 Add bot/service tests for disabled feature behavior, enabled feature prompt delivery, read callback success, dismiss callback, and provider failure without progress advancement.
- [x] 6.2 Run `ruff check .` and fix any lint failures.
- [x] 6.3 Run `ruff format --check .` and fix any formatting failures.
- [x] 6.4 Run `python3 -m compileall src` and fix any syntax issues.
- [x] 6.5 Run `pytest --tb=short -q` and fix any test failures.
