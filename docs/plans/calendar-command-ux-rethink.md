# Plan: Rethink calendar/reminder command UX and AI action flow

## Goal

Improve the Telegram UX for calendar and reminder actions so users do not need to type full structured commands in one line, while also making AI-driven reminder/calendar actions more reliable.

This plan covers discovery and architecture only.

## User problems to solve

- `/rem add YYYY-MM-DD HH:MM | text` is too rigid
- `/cal add start | end | title [| description]` is too rigid
- users want `/cal add` to become interactive
- users want quick list views like tomorrow and next 7 days
- AI currently fails to turn natural-language requests into reliable reminder/calendar actions
- AI can create reminders only through a brittle JSON proposal path and cannot create calendar events at all
- the current AI confirmation flow is unreliable: sometimes no approval is shown and nothing gets created

## Short answer: is interactive UX possible here?

Yes.

In Telegram, the bot cannot turn the slash-command composer itself into a rich multi-field form, but it **can** do the next best thing:

- use `/cal add` or `/rem add` as an intent launcher
- reply with follow-up questions
- use inline buttons / reply keyboards for common choices
- keep a short-lived draft state until the user confirms or cancels

That is the recommended direction.

## Current state

Relevant code paths:

- `src/personal_assistant_bot/bot.py`
  - `reminder_handler()` requires `/rem add YYYY-MM-DD HH:MM | text`
  - `calendar_handler()` requires `/cal list [days]` or `/cal add start | end | title [| description]`
  - `chat_handler()` sends the AI prompt, receives `reply` + optional `proposed_action`, and creates a pending approval only when `proposed_action` is present and valid
  - approval buttons already exist for AI-proposed actions
- `src/personal_assistant_bot/services.py`
  - `parse_local_datetime()` only accepts strict `YYYY-MM-DD HH:MM`
  - `create_reminder()` and `create_calendar_event()` already exist
  - `list_calendar_events(days=7)` already exists
  - `_execute_action()` supports `create_task`, `add_shopping_items`, `create_note`, `create_reminder`
  - `get_tool_snapshot()` already exposes reminders and a short agenda to AI
- `src/personal_assistant_bot/ai.py`
  - AI is limited to `SUPPORTED_ACTIONS = {create_task, add_shopping_items, create_note, create_reminder}`
  - reminder writes depend on the model emitting strict JSON in a fragile custom format
  - if the model returns plain text, malformed JSON, or an unsupported action, the app falls back to a normal reply and no confirm UI appears
- `src/personal_assistant_bot/calendar_integration.py`
  - calendar reads/writes already exist behind `CalendarService`

## Current failure mode to fix in AI confirmation

The intended design is already:

- AI interprets the user request
- AI returns a structured action proposal
- the app creates a pending approval
- the app shows confirm/deny buttons
- only after user confirmation does the backend write the reminder/calendar event

The current problem is that this chain is brittle at the **proposal generation** step.

Today, the confirm UI appears only if the model returns parseable JSON with a valid `proposed_action`. If any of the following happens, nothing is queued:

- the model replies in plain conversational text
- the JSON is malformed or wrapped in extra text the parser cannot recover from
- the model chooses an unsupported action type
- the model does not supply the exact fields the backend expects

That matches the observed failure: the assistant talked about creating a reminder, but no usable proposal reached the app, so no approval was created and `/rem list` stayed empty.

## Confirmed platform and docs behavior

Based on `python-telegram-bot` docs and examples:

- multi-step chat flows are supported via `ConversationHandler`
- inline buttons are built with `InlineKeyboardButton` + `InlineKeyboardMarkup`
- button clicks are handled with `CallbackQueryHandler`
- callback queries should be acknowledged with `query.answer()`
- persistent conversation state is supported, but a custom lightweight draft store is also viable

Based on OpenAI tool/structured output docs:

- structured outputs and tool/function calling are the recommended way to gather machine-usable fields
- tool schemas are more reliable than asking the model to emit ad hoc JSON text
- backend validation should remain authoritative before any write happens

## Chosen direction

Adopt a **dual-input architecture**:

1. keep strict one-line commands as optional power-user shortcuts
2. make guided conversational flows the primary UX for `/cal add` and later `/rem add`
3. unify interactive flows and AI writes behind one structured action proposal + approval pipeline
4. keep explicit user confirmation as the only write gate

This direction was reviewed with `@council` and is the recommended balance of UX, reliability, and rollout risk.

## Product decisions

### 1. Keep full one-line commands

Keep these working:

- `/rem add YYYY-MM-DD HH:MM | text`
- `/cal add YYYY-MM-DD HH:MM | YYYY-MM-DD HH:MM | title [| description]`

But reposition them as:

- shortcut mode
- advanced / fast path
- not the default documented experience

### 2. Make slash commands intent launchers

New mental model:

- `/cal add` starts a guided event-creation flow
- `/rem add` starts a guided reminder flow
- `/cal tomorrow` shows tomorrow
- `/cal next7` shows today + next 7 days rolling window
- `/cal nextweek` can exist as a friendly alias if desired, but `next7` should be the canonical unambiguous command

### 3. Add conversation draft state

Introduce a small per-chat/per-user draft object for in-progress flows.

Recommended fields:

- `flow_type` (`calendar_create`, `reminder_create`)
- `step`
- `title` / `message`
- `start_local`
- `end_local`
- `description`
- `timezone`
- `source` (`command`, `ai`)
- `expires_at`

Recommended behaviors:

- ask only for the next missing required field
- allow `/cancel`
- expire stale drafts automatically
- show a final human-readable preview before confirm

### 4. Unify writes behind one approval model

All write paths should produce the same internal proposal shape.

Suggested conceptual action types:

- `create_reminder`
- `create_calendar_event`

Suggested fields for `create_calendar_event`:

- `title`
- `start_local`
- `end_local`
- `description` optional
- `timezone`

This should be validated server-side and then routed through the same approval pipeline already used for AI proposals.

### 5. Improve AI action reliability in phases

Current problem:

- the AI is told to emit strict JSON text
- reminder actions are fragile
- calendar creation is not in `SUPPORTED_ACTIONS`
- the system prompt is too weak as an execution contract for write intents
- the app does not clearly surface when the model failed to produce a valid proposal

Recommended end state:

- AI uses structured tool/schema outputs when supported by the provider
- backend converts tool output into the same internal action proposal used by command flows
- if provider compatibility is needed, keep the current JSON proposal path as a temporary fallback

Important constraint:

- even after tool calling is added, AI should **not** directly execute writes
- it should still produce a proposal that requires explicit user confirmation

### 5a. Explicit plan to fix the broken confirm/tool-call path

The plan should include a dedicated reliability pass for AI write proposals.

#### Prompt / contract improvements

- rewrite the system prompt so it is explicit that for write intents the model must do exactly one of these:
  - ask a short follow-up question if required fields are missing or ambiguous
  - return a valid structured proposal for confirmation
- include concrete examples for reminder and calendar requests
- make it explicit that the assistant must not say an action was created before confirmation exists
- make the expected action payloads fully explicit, including label/preview text

#### Structured output improvements

- prefer actual tool calling or strict structured outputs over freeform JSON-in-text
- if JSON fallback remains, validate against a single action schema instead of loose dict handling
- add `create_calendar_event` to the supported AI action surface

#### App-side reliability improvements

- log raw AI responses and the proposal parsing outcome for debugging
- distinguish these cases in logs and user-facing behavior:
  - no structured response
  - malformed response
  - unsupported action
  - missing required payload fields
- fail closed but transparently: if the user clearly asked for a write and the model failed to produce a valid proposal, reply with something like:
  - `I understood that you want to create a reminder, but I couldn't prepare the confirmation yet.`
  - then either ask the missing field directly or route into the interactive draft flow

#### Confirmation UX rule

- once the model returns a valid proposal, the **app** owns confirmation
- the AI should propose; the app should create the pending approval and show buttons
- this keeps confirmation logic deterministic and prevents the model from pretending the write already happened

## Recommended UX flows

### `/cal add`

Preferred flow:

1. user sends `/cal add`
2. bot asks: `What is the title?`
3. user replies: `Jesus memorial`
4. bot asks: `When does it start?` with quick suggestions like `Tomorrow 20:00`, `Pick date`, `Cancel`
5. user replies in natural language or taps a suggestion
6. bot asks for end time only if not inferable or required by product rules
7. bot shows preview:

   - title
   - start
   - end
   - timezone
   - description if present

8. user confirms via inline button
9. bot creates the event and edits/replies with success

### `/rem add`

Preferred flow:

1. user sends `/rem add`
2. bot asks: `What should I remind you about?`
3. user replies: `Jesus memorial`
4. bot asks: `When should I remind you?` with quick suggestions
5. bot normalizes the interpreted local date/time
6. bot shows preview with timezone
7. user confirms

### AI message flow

Preferred flow:

1. user says: `add a calendar event tomorrow at 20 called Jesus memorial`
2. AI extracts structured fields
3. if anything is missing or ambiguous, AI asks one short follow-up question
4. once complete, AI proposes a structured action in the exact app-supported schema/tool format
5. bot shows approval buttons with a normalized preview
6. on confirm, backend executes the action

Failure handling requirement:

- if AI fails to produce a valid proposal, the app should not silently degrade into a useless conversational answer
- instead it should either ask the next missing question itself or clearly say confirmation could not be prepared

## Natural language date/time strategy

The current strict parser is good for deterministic shortcuts, but not for guided UX.

Recommended parsing model:

- preserve strict `YYYY-MM-DD HH:MM` support for shortcut mode
- add a second parser layer for guided and AI flows that accepts natural language such as:
  - `tomorrow 20`
  - `next friday at 3`
  - `today 18:30`
- always normalize to the chat timezone before preview/approval
- require clarification when interpretation is ambiguous

Ambiguity examples that should trigger clarification:

- missing AM/PM where locale makes it unclear
- vague terms like `later`, `evening`, `next week` when exact time is required
- event without an end time if product rules do not define a default duration

## List view changes

### Calendar

Add first-class list shortcuts:

- `/cal today`
- `/cal tomorrow`
- `/cal next7`

Optional alias:

- `/cal nextweek` -> same behavior as `next7`

Keep:

- `/cal list [days]` as the flexible fallback

Formatting recommendation:

- agenda format, not dense calendar format
- grouped by day
- clear empty states
- maximum item cap remains reasonable for chat readability

### Reminder views

No immediate command expansion is required for this request, but the same pattern could later add:

- `/rem today`
- `/rem tomorrow`

## Architecture shape

### Option A: `ConversationHandler`-driven flows

Pros:

- native fit for Telegram multi-step flows
- explicit states per flow
- good for command-first interactions

Cons:

- can become awkward if command flows and AI follow-ups must share the same logic

### Option B: lightweight generic draft engine

Pros:

- one model for both slash-command flows and AI follow-ups
- easier to unify with approval proposals
- better fit if multiple flows will reuse the same field collection logic

Cons:

- requires custom routing/state handling

### Recommended choice

Use a **lightweight generic draft engine**, not separate hardcoded flows per feature.

Reason:

- the bot already mixes deterministic commands and AI chat
- reminders and calendar should converge on the same field-collection and approval rules
- a shared draft model reduces duplicated logic across `/cal add`, `/rem add`, and AI-guided creation

## File-level planning notes

### `src/personal_assistant_bot/bot.py`

Planned direction:

- shift `/cal add` from strict argument-only mode to intent launcher + optional shortcut parsing
- do the same for `/rem add`
- add `/cal today`, `/cal tomorrow`, `/cal next7` handlers or subcommand branches
- route follow-up messages into the active draft flow before generic AI chat handling
- keep `/confirm` and `/reject` fallback behavior
- add clearer handling when AI write intent is detected but no valid proposal is produced, so the user is not left thinking something was created when nothing was queued

### `src/personal_assistant_bot/services.py`

Planned direction:

- add draft creation/update/clear helpers or integrate draft operations with storage
- separate strict datetime parsing from natural-language parsing
- add a canonical action proposal shape for reminder/calendar writes
- extend `_execute_action()` to support `create_calendar_event`
- centralize preview formatting and ambiguity checks
- validate action payload completeness before approval creation and return explicit user-safe errors

### `src/personal_assistant_bot/storage.py`

Planned direction:

- persist draft state if flows must survive process restarts
- otherwise start with in-memory drafts only if short-lived loss is acceptable
- if persisted, add TTL cleanup rules and chat/user scoping

### `src/personal_assistant_bot/ai.py`

Planned direction:

- extend action support to calendar events
- move toward structured tool/schema outputs instead of ad hoc strict-JSON prompting
- keep JSON proposal fallback during migration if backend compatibility requires it
- strengthen the system prompt with concrete examples and explicit write-intent rules
- add better parse/validation diagnostics so broken proposals are observable during testing

### `README.md` / help text

Planned direction:

- document the new recommended flows
- demote full inline syntax to shortcut/advanced mode
- document new list subcommands

## Risks and mitigations

### Risk: conversation state becomes messy

Mitigation:

- use one generic draft model
- add TTL expiry
- add `/cancel`
- scope drafts by `chat_id` + `user_id`

### Risk: AI and command paths drift apart

Mitigation:

- one canonical internal action proposal shape
- one approval pipeline
- one preview formatter

### Risk: natural-language times are parsed incorrectly

Mitigation:

- keep strict shortcut syntax available
- normalize to local timezone before preview
- clarify ambiguous inputs instead of guessing
- never write before explicit confirmation

### Risk: too many entry paths confuse users

Mitigation:

- define one recommended path in help text
- call one-line syntax a shortcut
- keep command names small and predictable

### Risk: AI still refuses to act

Mitigation:

- add reminder + calendar actions to the AI-visible tool surface
- stop relying only on prose instructions for JSON output
- validate action proposals server-side and present a clear approval preview

### Risk: AI appears to confirm a write, but the app never queued it

Mitigation:

- treat proposal generation as a first-class failure case
- add explicit observability for parse/proposal failures
- never let a plain conversational reply masquerade as a pending action
- route failed write intents into a follow-up question or interactive draft instead of dead-ending

## Phased rollout

### Phase 1: low-risk UX wins

- add `/cal today`
- add `/cal tomorrow`
- add `/cal next7`
- optionally alias `/cal nextweek`
- update help text to position current full-syntax commands as shortcuts

### Phase 2: guided calendar creation

- add draft-state flow for `/cal add`
- end with preview + confirm/cancel

### Phase 3: AI calendar support

- add `create_calendar_event` to the action model and approval executor
- expose calendar creation to AI proposals
- fix the reminder/calendar proposal reliability path so confirmation always appears when a valid proposal exists
- improve prompt/schema quality so AI asks for missing data instead of pretending it acted

### Phase 4: guided reminder creation

- apply the same draft flow to `/rem add`
- improve natural-language reminder parsing and previewing

### Phase 5: AI action architecture cleanup

- introduce a shared schema/tool definition for assistant write proposals
- use tool calling / structured outputs when supported
- keep JSON proposal fallback only as compatibility path

## Validation plan

Implementation should be considered successful when:

1. `/cal add` works without requiring full inline syntax
2. `/rem add` can be launched interactively
3. `/cal tomorrow` works
4. `/cal next7` works as a rolling today + 7 days view
5. AI can reliably propose reminder creation from natural language
6. AI can propose calendar event creation
7. all reminder/calendar writes still require explicit user confirmation
8. shortcut syntax still works for power users
9. when AI fails to produce a valid write proposal, the user gets a clear follow-up or error instead of a fake success path
10. observed cases like the broken reminder example no longer end with "nothing happened"

## Open questions to resolve before implementation

- Should event creation require an explicit end time, or should the bot apply a default duration when omitted?
- Should draft state survive bot restarts, or is volatile short-lived state acceptable for v1?
- Do you want `/cal nextweek` to mean rolling 7 days, or literal next calendar week? This plan recommends `next7` as canonical because it is unambiguous.
- Should guided flows use inline buttons only for suggestions, or also use Telegram reply keyboards for common time choices?

## Recommendation summary

Keep the current strict commands as shortcut mode, but make `/cal add` and `/rem add` interactive via short-lived conversational drafts. Add `/cal tomorrow` and `/cal next7` as first-class views. Unify command-driven and AI-driven writes behind one structured proposal + approval pipeline, and extend that pipeline to calendar creation. Migrate AI from brittle custom JSON output toward schema/tool-based proposals, but keep explicit human confirmation as the only execution gate.
