## Why

Oscar should support a lightweight daily Bible reading habit without relying on the user to remember to ask for the next chapter. The MVP should keep the interaction calm: one daily reminder, one chapter only when explicitly requested, always in Portuguese.

## What Changes

- Add a new Bible feature group that can be enabled by configuration without affecting existing assistant features.
- Send one configurable daily Telegram prompt asking whether the user is ready for the next Bible chapter.
- Provide inline actions for the prompt, with a primary action that fetches and sends the next sequential chapter only when clicked.
- Track each chat/user's Bible reading progress so the next chapter advances sequentially after a successful read.
- Avoid catch-up spam: missed days do not enqueue multiple chapters or send multiple prompts; each daily prompt can result in at most one chapter.
- Fetch Portuguese chapter text from an external Bible API for the MVP, with ABíbliaDigital as the preferred provider.
- Optionally use the configured AI backend to format or summarize the fetched chapter for Telegram delivery, while preserving the Portuguese-only experience.

## Capabilities

### New Capabilities
- `daily-bible-reading`: Portuguese-only daily Bible reading prompts, sequential chapter progress, chapter retrieval, and one-chapter-per-click delivery.

### Modified Capabilities
- None.

## Impact

- Configuration: add Bible-specific settings for enablement, provider credentials, translation, and daily notification time.
- Storage: add persistent Bible progress and daily prompt state.
- Scheduler: add a daily Bible prompt alongside existing proactive notifications without creating backlog/catch-up behavior.
- Telegram bot: add inline callback handling for Bible prompt actions and optional deterministic commands for status/configuration.
- Integrations: add an API client for Portuguese Bible chapter retrieval, initially targeting ABíbliaDigital.
- AI backend: optionally route chapter text through the existing OpenAI-compatible backend for Portuguese formatting/resume behavior when configured.
- Tests: cover config activation, progress advancement, no-spam scheduling, callback behavior, and API/client error handling.
