# Plan: calendar reliability, unified AI tools, and kbplus integration

## Goal

Plan the next work for Oscar without implementing it yet.

Requested scope:

1. fix calendar event reading because briefing output currently falls back to `- Upcoming calendar: none or unavailable`
2. move Oscar toward unified theme-based AI tools instead of one tool/action per verb
3. support multiple tool calls in one AI request
4. plan kbplus kanban integration, including a kbplus settings option to generate an API token for external integrations
5. ignore task `#5` for now
6. treat task `#6` as the unified-command / multiple-task-creation direction above

This document is discovery + architecture only.

## Repos inspected

- Oscar: `/Users/gustavocaiano/docs/github/oscar`
- KB+: `/Users/gustavocaiano/docs/github/kbplus/app`

## Current state summary

### Oscar calendar path

Relevant files:

- `src/personal_assistant_bot/calendar_integration.py`
- `src/personal_assistant_bot/services.py`
- `src/personal_assistant_bot/bot.py`
- `tests/test_hours_and_calendar.py`
- `tests/test_services_core.py`

Observed behavior:

- `AssistantService.get_tool_snapshot()` tries to load a short agenda for AI/briefing use
- if `CalendarIntegrationError` happens, the error is swallowed and `agenda_entries = []`
- `AssistantService.build_briefing()` then prints `- Upcoming calendar: none or unavailable`

Important detail in current implementation:

- `CalendarService._get_calendar()` uses `principal.calendars()` and matches `CALDAV_CALENDAR_NAME` via `getattr(calendar, "name", None)`
- upstream `python-caldav` examples/source prefer `principal.get_calendars()` / `principal.calendar(name=...)` and `calendar.get_display_name()`
- that makes Oscar's current lookup likely brittle, especially for iCloud/CalDAV display-name handling

### Oscar AI/tool-call path

Relevant files:

- `src/personal_assistant_bot/ai.py`
- `src/personal_assistant_bot/services.py`
- `src/personal_assistant_bot/storage.py`
- `src/personal_assistant_bot/bot.py`
- `tests/test_approval_and_scheduler.py`

Observed behavior:

- Oscar currently uses custom JSON-in-text, not provider-native tool calling
- `ai.py` instructs the model to propose **exactly one** supported action
- `AIResponse` holds one `proposed_action`
- approvals store one `action_type` + one `payload_json`
- `_execute_action()` executes one action only
- bot approval UX assumes one approval token maps to one action

Current AI action surface:

- `create_task`
- `add_shopping_items`
- `create_note`
- `create_reminder`
- `create_calendar_event`

### KB+ integration surface

Relevant files:

- `app/prisma/schema.prisma`
- `app/src/auth.ts`
- `app/src/lib/session.ts`
- `app/src/lib/board-service.ts`
- `app/src/app/api/boards/[boardId]/tasks/route.ts`
- `app/src/app/api/boards/[boardId]/tasks/[taskId]/route.ts`
- `app/src/components/boards/boards-index-client.tsx`

Observed behavior:

- KB+ is a Next.js + Auth.js + Prisma app with session-based route protection
- there is no settings/account/preferences page today
- existing task APIs are session-authenticated browser APIs, not external integration APIs
- Prisma schema has `User`, `Board`, `BoardMember`, `BoardColumn`, `Task`, but no personal access token / API token model

## Confirmed external behavior

### OpenAI-compatible tool calling

OpenAI Chat Completions docs confirm:

- `tools` can be supplied on the request
- responses can include a `tool_calls` array
- multiple tool calls can be allowed in one turn with `parallel_tool_calls=true`

This supports the requested multi-tool-call direction, as long as Oscar introduces an internal adapter and does not couple business logic directly to one provider response shape.

### python-caldav behavior

From upstream examples/source:

- `principal.get_calendars()` is the preferred API
- `principal.calendars()` is a backwards-compatibility alias
- display-name lookup is done through `principal.calendar(name=...)` / `calendar.get_display_name()`

That strongly suggests Oscar should stop relying on `calendar.name` for matching `CALDAV_CALENDAR_NAME`.

## Chosen direction

This direction was reviewed with `@council`.

Chosen architecture:

1. fix calendar reliability first
2. replace the single-action AI contract with an internal **tool registry + execution plan** model
3. expose **one AI tool per theme/domain**, not one tool per verb
4. allow **multiple tool calls per user turn**
5. keep approvals, but approve a **bundle/plan** rather than one action at a time
6. integrate KB+ through a **token-authenticated external API**, not direct DB coupling and not reused browser session endpoints

## Workstream 1: calendar read reliability

### Problem to solve

Right now the user cannot tell whether:

- there are truly no upcoming events
- Oscar failed to connect to CalDAV
- the configured calendar name did not resolve
- event parsing failed after a successful query

All of those collapse into the same user-facing output.

### Planned direction

#### 1. Make calendar resolution more robust

Refactor `CalendarService._get_calendar()` to prefer:

1. a stable configured calendar identifier/URL if later added
2. `principal.calendar(name=...)`
3. `principal.get_calendars()` plus `get_display_name()` matching
4. first-calendar fallback only when no explicit calendar is configured

Matching rules should be:

- trimmed
- case-insensitive
- logged when no exact match is found

#### 2. Stop hiding calendar failures inside snapshots

Change the snapshot contract so Oscar can distinguish:

- `ok`
- `empty`
- `unavailable`
- `error`

Recommended shape:

```json
{
  "agenda_status": "ok|empty|unavailable|error",
  "agenda_error": "optional human-readable reason",
  "agenda": []
}
```

#### 3. Improve briefing output

Replace the current ambiguous text with explicit states such as:

- `- Upcoming calendar: none`
- `- Upcoming calendar: unavailable (calendar 'Work' was not found)`
- `- Upcoming calendar: unavailable (authentication failed)`

#### 4. Add observability

Add targeted logging around:

- CalDAV principal/calendar discovery
- matched calendar display name / URL
- upstream read failures
- malformed or unsupported event payloads

### File-level impact

- `src/personal_assistant_bot/calendar_integration.py`
- `src/personal_assistant_bot/services.py`
- `README.md`
- tests in `tests/test_hours_and_calendar.py` and `tests/test_services_core.py`

### Validation to add later

- configured but unavailable calendar returns explicit status
- name mismatch returns clear error text
- empty calendar returns `none`, not `unavailable`
- successful read still populates briefing and AI snapshot agenda

## Workstream 2: unified theme-based AI tools

### Product direction

Move from verb-specific actions like `create_task` to theme/domain tools like:

- `tasks`
- `shopping`
- `notes`
- `reminders`
- `calendar`

Each tool should accept an operation and arguments.

Example conceptual shapes:

```json
{ "tool": "tasks", "operation": "create", "args": { "title": "Pay rent" } }
{ "tool": "tasks", "operation": "create_many", "args": { "titles": ["A", "B", "C"] } }
{ "tool": "tasks", "operation": "complete", "args": { "id": 12 } }
{ "tool": "reminders", "operation": "list", "args": { "pending_only": true } }
```

### Why this direction

- matches the user's request for one tool per theme
- makes the AI surface more stable as operations grow
- avoids exploding the number of top-level tool names
- fits multi-call planning better than one-verb-per-tool naming

### Recommended internal architecture

#### 1. Internal tool registry

Introduce an internal registry that defines for each domain tool:

- supported operations
- input schema/validation
- read-only vs mutating classification
- approval policy
- execution handler

#### 2. Execution-plan model

Replace the single `proposed_action` mental model with an execution plan that can contain multiple actions.

Recommended conceptual shape:

```json
{
  "reply": "I prepared 3 task actions for confirmation.",
  "tool_plan": {
    "steps": [
      {"tool": "tasks", "operation": "create", "args": {"title": "A"}},
      {"tool": "tasks", "operation": "create", "args": {"title": "B"}},
      {"tool": "reminders", "operation": "create", "args": {"when_local": "2026-04-03 09:00", "message": "C"}}
    ]
  }
}
```

#### 3. Bundled approvals

Keep user confirmation, but approve one plan/bundle per turn.

Execution behavior should be:

- sequential
- per-step validated
- per-step result tracked
- explicit about partial failure

Do **not** promise all-or-nothing rollback across local DB + future external integrations.

### Storage evolution

Current approvals table is single-action shaped.

Planned evolution:

- introduce an approval request model that can store many planned steps
- keep status at both request level and per-step level

Suggested statuses:

- request: `pending`, `executing`, `executed`, `partially_executed`, `failed`, `rejected`, `expired`
- step: `pending`, `executed`, `failed`, `skipped`

### Migration strategy

Phase the migration so Oscar can briefly support both:

- legacy single-action proposals
- new multi-step tool plans

That reduces rollout risk and avoids a one-shot rewrite.

### File-level impact

- `src/personal_assistant_bot/ai.py`
- `src/personal_assistant_bot/services.py`
- `src/personal_assistant_bot/storage.py`
- `src/personal_assistant_bot/bot.py`
- tests in `tests/test_approval_and_scheduler.py`

## Workstream 3: provider-native tool calling + multiple tool calls

### Current limitation

Oscar currently asks the model to emit strict JSON text. That is fragile and hard-limits the system to one action.

### Planned direction

Adopt provider-native tool calling as the primary path.

Requirements:

- send real `tools`
- allow `tool_calls[]`
- enable multiple tool calls per turn
- normalize provider responses into Oscar's internal `tool_plan`

### Important design rule

Do not let provider response shapes leak into domain logic.

Recommended layering:

1. AI provider adapter parses native tool calls
2. adapter normalizes them into Oscar's internal plan format
3. service layer validates the plan
4. approval layer owns confirmation + execution

### Read vs write behavior

Recommended rule:

- mutating actions stay approval-gated
- read-only actions may later execute immediately if desired, but that should be an explicit later product decision

For the first rollout, keep the model simple:

- all write-capable plans require confirmation
- read operations can still be answered from the existing tool snapshot unless live reads are intentionally added

## Workstream 4: KB+ integration model

### Chosen boundary

Integrate Oscar with KB+ through a dedicated external API.

Do **not**:

- read/write KB+ database tables directly from Oscar
- reuse the existing session-auth browser endpoints for external automation

### Why

- cleaner security boundary
- less coupling to KB+ internals
- supports later revocation, auditing, and scoped access

### Recommended KB+ auth model

Add personal access tokens / integration tokens in KB+.

Recommended data model:

- `id`
- `userId`
- `name`
- `tokenPrefix`
- `tokenHash`
- `scopes`
- `expiresAt` optional
- `lastUsedAt`
- `revokedAt`
- timestamps

Rules:

- show plaintext token once
- store only a hash
- allow revoke/regenerate
- log last use

### Recommended KB+ API namespace

Use a dedicated route family such as:

- `/api/integrations/v1/boards`
- `/api/integrations/v1/boards/:boardId/tasks`

Bearer token auth should be separate from Auth.js session auth.

### Scope model

Start coarse and simple:

- `boards:read`
- `tasks:read`
- `tasks:write`

Authorization should still enforce the token owner's board access at request time.

### Sync direction

Start with **one-way Oscar -> KB+**.

Interpretation:

- KB+ becomes the external kanban system Oscar can create/update tasks in
- Oscar remains free to keep its local task list for now unless later intentionally migrated
- avoid two-way sync, conflict resolution, and webhooks in v1

### Oscar-side abstraction

Plan for task backend abstraction on Oscar's side, e.g.:

- local task backend
- KB+ task backend

That keeps the new `tasks` tool from being hard-coded to one storage target forever.

### KB+ UI direction

There is no settings page today.

Natural future location:

- add a Settings entry from `app/src/components/boards/boards-index-client.tsx`
- create a user settings page where tokens can be created/revoked

## Planned `kbplus-changes.md`

When implementation work begins, Oscar should also produce a file named `kbplus-changes.md` describing the KB+ work needed in the other repo.

That future document should include:

- Prisma schema additions for tokens
- token hashing + verification middleware
- integration route list
- settings page/navigation work
- request/response contracts Oscar will depend on
- security notes and rollout steps

## Rollout plan

### Phase 1 — calendar reliability

- fix CalDAV calendar lookup
- stop swallowing snapshot errors
- separate `empty` from `unavailable`
- improve briefing/user-facing diagnostics

### Phase 2 — internal tool registry

- define theme-based tools and operation schemas
- introduce internal execution-plan model
- keep temporary compatibility with legacy single-action approvals

### Phase 3 — bundled approvals

- evolve storage from single-action approvals to request + steps
- update approval UX and execution tracking

### Phase 4 — native multi-tool AI path

- switch provider integration to real tool calls
- support `tool_calls[]`
- support multiple task/reminder/calendar actions in one turn

### Phase 5 — KB+ contract artifact

- write `kbplus-changes.md`
- finalize Oscar config contract for KB+ base URL/token/board mapping

### Phase 6 — KB+ implementation

- add token model and settings UI in KB+
- add integration API routes
- add Oscar KB+ backend integration

## Risks and mitigations

### Risk: partial execution with multi-step plans

Mitigation:

- execute sequentially
- track per-step results
- report partial failures clearly

### Risk: provider lock-in

Mitigation:

- use provider-native tool calls only behind an internal adapter
- keep Oscar's internal plan format provider-agnostic

### Risk: CalDAV server quirks

Mitigation:

- support stable calendar identifiers later if needed
- improve logging and diagnostics
- add tests for name mismatch and empty/unavailable states

### Risk: KB+ token security

Mitigation:

- hash tokens at rest
- show plaintext once
- add scopes, revocation, and last-used tracking

### Risk: approval UX gets too noisy

Mitigation:

- approve one compact bundle per user turn
- show a readable preview summarizing all planned steps

## Open questions to settle before implementation

1. Should Oscar keep local tasks and optionally mirror to KB+, or should a configured KB+ workspace become the primary task backend for selected chats/users?
2. How should Oscar choose the target KB+ board/column for created tasks?
3. Do read-only AI tools later need live execution, or is snapshot-based read context enough for now?
4. Should calendar configuration grow from display name to explicit calendar URL/ID once the reliability pass is done?

## Recommended first implementation milestone

Start with the calendar reliability fix only.

Why:

- smallest scope
- directly user-visible
- isolated from the larger AI/tooling refactor
- produces better diagnostics before the broader tool-call redesign
