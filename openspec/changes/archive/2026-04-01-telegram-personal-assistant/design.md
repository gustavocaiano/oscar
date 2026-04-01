## Context

This project is starting from a nearly empty repository after the prior generic chat-bot direction was intentionally discarded. The new target is a Telegram-first personal assistant that combines deterministic personal tools with AI-assisted chat, keeping the experience simple and useful for daily life rather than building a large autonomous agent system.

The assistant needs to support both slash-command workflows and default chat behavior. Structured tools will cover tasks, shopping, reminders, notes, calendar actions, and hour tracking. The hour-tracking feature should borrow proven behavior from the existing `hcounter` repository, while Apple/iCloud calendar support should use CalDAV rather than Google APIs. The AI layer will use an OpenAI-compatible backend and must ask for confirmation before writing changes when triggered from free-form chat.

## Goals / Non-Goals

**Goals:**
- Build a single Python Telegram bot with multiple useful personal-assistant capabilities.
- Use grouped command namespaces such as `/cal-*` and `/h-*` so features stay organized.
- Keep a local SQLite database as the system of record for assistant-managed data.
- Support proactive assistant messages such as morning briefings, reminder alerts, hour reminders, and evening wrap-ups.
- Reuse or port reliable hour-tracking logic from `hcounter` instead of reinventing its parsing behavior.
- Support AI chat that can inspect assistant data, suggest actions, and request confirmation before modifying stored state.

**Non-Goals:**
- Building a fully autonomous agent that performs unbounded multi-step actions without user approval.
- Implementing large-scale team/multi-user collaboration or a web dashboard in the initial version.
- Supporting every Apple ecosystem API natively; calendar scope is limited to iCloud/CalDAV integration.
- Replacing dedicated calendar/task platforms entirely in the first release.

## Decisions

### 1. Use one Python Telegram bot with modular feature services
- **Decision:** The assistant will be a single Python app with separate modules/services for AI chat, tasks, shopping, reminders, notes, calendar, and hour tracking.
- **Why:** One bot process keeps the product simple for a solo user while modular code keeps feature growth manageable.
- **Alternatives considered:**
  - **Multiple microservices:** unnecessary operational complexity for the first version.
  - **Monolithic handlers with no domain modules:** faster at first, but becomes brittle as features grow.

### 2. Organize deterministic commands by feature prefix
- **Decision:** Commands will be grouped by capability, for example `/task-add`, `/task-list`, `/shop-add`, `/rem-add`, `/cal-list`, `/cal-add`, `/h-add`, `/h-month`, `/note-add`.
- **Why:** A prefix-based command design stays understandable as the assistant gains more tools.
- **Alternatives considered:**
  - **One overloaded generic command:** hard to discover and document.
  - **Chat-only natural language for everything:** convenient, but less predictable and harder to support reliably.

### 3. Keep SQLite as the local source of truth for assistant-managed entities
- **Decision:** Tasks, shopping items, reminders, notes, pending approvals, chat memory, and assistant configuration will be stored in SQLite.
- **Why:** SQLite is easy to run inside Docker, fits a personal-use assistant, and keeps the initial deployment lightweight.
- **Alternatives considered:**
  - **Postgres:** more scalable, but unnecessary for an MVP.
  - **External-only storage:** would increase integration complexity before the core UX is proven.

### 4. Treat AI chat as a read-capable planner with confirmation-before-write
- **Decision:** Normal messages without a command will go to the AI backend, which may inspect assistant data and propose actions; write operations originating from chat will require explicit user confirmation before execution.
- **Why:** This preserves the value of natural-language interaction without making the assistant dangerously autonomous.
- **Alternatives considered:**
  - **Read-only AI:** safer, but less useful as a personal assistant.
  - **AI writes immediately:** higher convenience, but too risky for early trust and correctness.

### 5. Use scheduled jobs for proactive assistant behavior
- **Decision:** Morning briefs, reminder alerts, hour reminders, and evening wrap-ups will be implemented with scheduled jobs tied to stored user preferences and timezone settings.
- **Why:** Proactive messages are a core differentiator from a passive chat wrapper.
- **Alternatives considered:**
  - **Manual-only workflows:** simpler, but misses much of the assistant value.
  - **Heavy workflow engine first:** too much infrastructure for the initial scope.

### 6. Integrate Apple Calendar via CalDAV
- **Decision:** Calendar support will target iCloud Calendar through CalDAV using app-specific credentials and basic event operations.
- **Why:** The user does not use Google Calendar, and CalDAV is the practical interoperable path for Apple/iCloud calendar integration.
- **Alternatives considered:**
  - **Google Calendar integration:** mismatched with the user's actual workflow.
  - **Local-only calendar in SQLite:** easier to build, but lower day-to-day usefulness if it does not sync with real calendar data.

### 7. Reuse `hcounter` behavior by porting domain logic, not depending on the repo at runtime
- **Decision:** Relevant hour-tracking logic from `hcounter` will be ported or adapted into this repository rather than creating a hard runtime dependency on the external repo.
- **Why:** This preserves known-good behavior while keeping deployment self-contained.
- **Alternatives considered:**
  - **Import from sibling repo at runtime:** fragile deployment coupling.
  - **Rewrite from scratch:** unnecessary duplication and higher regression risk.

## Risks / Trade-offs

- **[Feature scope grows too quickly]** → Start with clearly separated feature modules and command namespaces so the initial implementation can prioritize the highest-value flows first.
- **[AI-triggered writes could make unwanted changes]** → Require confirmation tokens or explicit approval commands before any write proposed from free-form chat is executed.
- **[CalDAV setup may be awkward for users]** → Keep calendar scope narrow, document iCloud app-specific password setup, and allow the rest of the assistant to work without calendar enabled.
- **[Scheduled briefings can become noisy]** → Store per-user preferences for enabled proactive messages and scheduled times.
- **[Porting `hcounter` logic may drift from the original behavior]** → Preserve tests and example command formats from `hcounter` when adapting the hour-tracking feature.

## Migration Plan

1. Create the Python assistant bot skeleton, configuration loading, and modular service boundaries.
2. Define the SQLite schema for assistant entities and approval workflow state.
3. Implement deterministic command-based features first: tasks, shopping, notes, reminders, hour tracking, and basic calendar operations.
4. Port/adapt the required `hcounter` parsing and aggregation logic into the new project.
5. Add the AI chat layer with read access to assistant tools and confirmation-before-write behavior.
6. Add scheduled proactive messages and briefing generation.
7. Validate each feature independently, then validate mixed workflows such as “what do I have to do today?” using both AI and structured data.

## Open Questions

- Should shopping and tasks share one generalized list model with different categories, or should they remain separate entities for clearer UX?
- Should confirmation for AI-proposed writes happen through inline buttons, follow-up slash commands, or plain-text replies?
- What timezone, morning-brief time, and evening-wrap-up time should be the initial defaults?
- Should calendar support be read/add only at first, or include event updates and deletions in the first implementation?
