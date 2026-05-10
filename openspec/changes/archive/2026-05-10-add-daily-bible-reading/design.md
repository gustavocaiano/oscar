## Context

Oscar is a Python 3.12 Telegram assistant with optional feature groups configured through `Settings`, SQLite-backed state, and a proactive notification loop that already handles morning briefings, hour reminders, evening wrap-ups, and timed reminders. The Bible MVP should follow those patterns while keeping the experience intentionally low-noise: one daily invitation, no backlog, and no automatic chapter delivery unless the user clicks.

The user prefers Portuguese-only Bible content and does not want a self-hosted Bible corpus for the MVP. ABíbliaDigital is the preferred external provider because it supports full chapter fetches in Portuguese translations such as NVI, ACF, RA, and ARC. The existing OpenAI-compatible backend can be used as the “cliproxy” path for Portuguese summary/formatting when available, but Bible delivery must remain useful even if AI formatting fails.

## Goals / Non-Goals

**Goals:**
- Add a separately configurable Bible feature group that is disabled by default.
- Send one daily Bible reading prompt per eligible chat at a configured local time.
- Send at most one chapter per user click and never send accumulated chapters for missed days.
- Track sequential reading progress from Genesis onward using Portuguese book metadata and chapter counts.
- Fetch chapter text from ABíbliaDigital using a Portuguese translation, defaulting to `nvi`.
- Format Telegram delivery safely, including long chapter splitting when needed.
- Optionally ask the AI backend for a concise Portuguese resume/reflection around the chapter while preserving the chapter text.

**Non-Goals:**
- No self-hosted Bible text corpus in the MVP.
- No random-hour scheduling in the MVP.
- No multi-language Bible support in the MVP.
- No catch-up queue, streaks, achievements, reading plans beyond canonical sequential order, or multi-translation comparison in the MVP.
- No AI-generated theological interpretation requirement; AI output is formatting/supporting context, not authoritative scripture text.

## Decisions

### 1. Use an API-first provider adapter, with ABíbliaDigital as the initial provider

ABíbliaDigital supports direct chapter retrieval via `GET /verses/{version}/{book}/{chapter}` and Portuguese translations. Implement a `BibleService` / provider client that accepts base URL, optional token, translation, and timeout.

Alternatives considered:
- **Self-hosted JSON corpus:** best reliability long-term, but explicitly not desired for MVP.
- **bible-api.com:** no auth and simple, but weaker Portuguese coverage.
- **api.bible:** broad catalog, but requires API keys and has more complex Bible/chapter identifiers.

### 2. Make activation explicit with `BIBLE_ENABLED`

Bible prompts are proactive, so the feature must not become active merely because defaults exist. Add `BIBLE_ENABLED=false` by default, plus settings such as `BIBLE_API_BASE_URL`, `BIBLE_API_TOKEN`, `BIBLE_TRANSLATION`, `BIBLE_DAILY_TIME`, and `BIBLE_TIMEOUT_SECONDS`.

`BIBLE_API_TOKEN` should be optional for development because ABíbliaDigital allows limited unauthenticated use, but production should use a token to avoid rate-limit surprises.

### 3. Store Bible progress separately from generic chat preferences

Use a dedicated `bible_reading_progress` table keyed by `chat_id` with fields such as:
- `chat_id`, `user_id`
- `enabled`
- `translation`
- `next_book`, `next_chapter`
- `chapters_read`
- `last_read_at`, `updated_at`, `created_at`

This avoids expanding the already broad `chat_preferences` dataclass for a feature-specific concern and keeps later Bible-specific preferences isolated.

### 4. Use a Bible-specific daily prompt claim table to avoid scheduler migration risk

The existing `scheduled_claims.notification_type` has a restrictive SQLite `CHECK` constraint for current notification types. Extending it requires a careful table rebuild migration for existing databases. For the MVP, use a dedicated `bible_daily_prompt_claims` table:

- `chat_id`
- `prompt_date`
- `status` (`claiming`, `sent`)
- `claimed_at`, `updated_at`
- primary key `(chat_id, prompt_date)`

The scheduler only evaluates the current local date. If the bot is offline for five days, no rows are created for missed dates, so no backlog can accumulate.

### 5. Keep the daily prompt as an invitation, not a chapter delivery

The scheduled message should be short and include inline actions:

```
📖 Pronto para o próximo capítulo da Bíblia?

[Ler capítulo] [Hoje não]
```

Clicking “Ler capítulo” fetches and sends exactly the current `next_book`/`next_chapter`, then advances progress only after successful delivery. Clicking “Hoje não” dismisses/edits the prompt without changing reading progress.

### 6. Use static book metadata, not static Bible text

Sequential advancement needs canonical book order and chapter counts. Store this as small in-code metadata containing ABíbliaDigital Portuguese abbreviations and chapter counts for the 66 books. This is not self-hosting scripture text and keeps the next-chapter calculation deterministic without extra API calls.

### 7. Treat AI formatting as graceful enhancement

When both Bible and backend AI are configured, the chapter delivery flow can send the fetched Portuguese text to the AI backend with a constrained Portuguese prompt asking for a short resume/reflection and readable formatting. If the backend is disabled or errors, Oscar should send the formatted chapter text directly rather than blocking the reading.

The scripture text returned by the provider remains the source of truth; progress advances based on provider fetch and Telegram delivery, not AI commentary quality.

## Risks / Trade-offs

- **External API outage or rate limit** → Show a clear Portuguese error and do not advance progress. Keep provider code isolated so fallback providers can be added later.
- **Translation availability changes** → Validate configured translation against a known Portuguese allowlist and fail fast with a user-visible configuration error.
- **Long chapters exceed Telegram limits** → Split messages into safe chunks and test with long chapters such as Psalm 119.
- **Duplicate scheduler workers** → Use the Bible prompt claim table with atomic insert semantics, mirroring the current scheduled notification claim pattern.
- **Prompt delivered but button clicked days later** → The read action should always fetch the current next chapter once; stale prompt dates should not create backlog. The callback can still work unless the message is unavailable, because progress is stored independently.
- **AI adds unwanted commentary** → Keep AI prompt constrained, preserve raw verse text, and allow raw fallback. Avoid making AI commentary normative.

## Migration Plan

1. Add new SQLite tables with `CREATE TABLE IF NOT EXISTS` during storage initialization:
   - `bible_reading_progress`
   - `bible_daily_prompt_claims`
2. No destructive migration is required for existing data.
3. Existing deployments remain unchanged until `BIBLE_ENABLED=true` is set.
4. Rollback is safe by disabling `BIBLE_ENABLED`; unused Bible tables can remain in the database.

## Open Questions

- Default daily time should be configurable; use a conservative default such as `09:00` unless the deployment environment specifies another value.
- Default translation should be `nvi` for MVP, with support for Portuguese alternatives such as `acf`, `ra`, and `arc` if confirmed by provider behavior.
