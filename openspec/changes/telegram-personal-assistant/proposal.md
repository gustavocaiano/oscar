## Why

The previous direction was too close to a generic chat wrapper, so the new goal is a Telegram-first personal assistant that stores real personal state and helps with day-to-day life. It should combine normal command-based features with AI-assisted chat, allowing the assistant to read personal data and propose actions while asking for confirmation before making changes.

## What Changes

- Build a Python Telegram bot that acts as a personal assistant rather than a plain chat client.
- Add structured personal tools for tasks, shopping items, reminders, notes/inbox capture, calendar access, and hour tracking.
- Reuse the existing hour-tracking behavior from `~/docs/github/hcounter` for logging hours, viewing month totals, and daily hour reminders.
- Add Apple/iCloud calendar support through CalDAV for agenda listing and basic event creation.
- Add an AI conversation mode for non-command messages that can inspect personal data, suggest actions, and ask for confirmation before writing changes.
- Add scheduled assistant behavior such as morning briefings, reminder alerts, hour reminders, and evening wrap-ups.
- Keep all assistant data in local SQLite storage for the initial version.

## Capabilities

### New Capabilities
- `assistant-chat-and-approvals`: Handle non-command chat through an AI backend with tool access, conversational context, and confirmation-before-write behavior.
- `task-and-shopping-management`: Create, list, update, and complete personal tasks and shopping items through Telegram commands and AI-assisted flows.
- `notes-and-inbox-capture`: Capture lightweight notes, ideas, and inbox items for later retrieval and briefing.
- `reminder-and-briefing-scheduler`: Schedule reminders and send proactive assistant messages such as morning briefs, reminder alerts, hour reminders, and evening summaries.
- `icloud-calendar-integration`: Read upcoming agenda items and create basic events in Apple/iCloud Calendar via CalDAV.
- `hcounter-hour-tracking`: Integrate reusable hour-tracking functionality from `hcounter`, including hour logging, monthly totals, and hour reminder behavior.

### Modified Capabilities
- None.

## Impact

- New Python bot application code for Telegram handling, AI orchestration, approval workflows, scheduling, and persistence.
- New SQLite schema covering assistant state such as tasks, shopping items, reminders, notes, approvals, and assistant memory.
- New calendar integration code and configuration for iCloud/CalDAV access.
- Reuse or port of domain logic from the external `hcounter` repository.
- Continued dependency on an OpenAI-compatible backend for AI chat behavior, with explicit separation between AI-assisted features and deterministic command-based features.
