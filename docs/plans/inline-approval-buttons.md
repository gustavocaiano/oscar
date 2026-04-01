# Plan: Inline approval buttons for AI-proposed actions

## Goal

Replace the current text-based approval UX:

- `/confirm <token>`
- `/reject <token>`

with Telegram inline buttons on the bot message itself:

- `Confirm`
- `Deny`

while preserving the existing approval safety model and keeping slash commands as a fallback path.

## Why this change

The current approval flow works, but it is friction-heavy:

- the user must copy or retype a token
- the bot message does not feel interactive
- approval is slower than it needs to be for common assistant actions

Inline buttons improve the experience without changing the underlying confirmation guarantees.

## Current state

Relevant code paths:

- `src/personal_assistant_bot/bot.py`
  - `chat_handler()` creates pending approvals and tells the user to run `/confirm` or `/reject`
  - `confirm_handler()` and `reject_handler()` execute approval decisions via command arguments
- `src/personal_assistant_bot/services.py`
  - `create_pending_approval()` creates the approval token and stores the action
  - `confirm_approval()` and `reject_approval()` handle state transitions safely

The existing domain/service layer is already good enough for button-driven confirmation. The main missing piece is Telegram callback handling.

## Confirmed Telegram / library behavior

Based on `python-telegram-bot` docs and examples:

- inline buttons are built with `InlineKeyboardButton` + `InlineKeyboardMarkup`
- button clicks are handled with `CallbackQueryHandler`
- callback queries should always be acknowledged with `await query.answer()`
- `query.data` must be treated as untrusted input and validated on the server side
- editing the original bot message is the normal pattern after a button is pressed

## Chosen direction

### Primary UX

When the AI proposes an action, the bot should send a message like:

> Proposed action: Add “cat food” to shopping list

with inline buttons:

- `Confirm`
- `Deny`

### Fallback UX

Keep `/confirm <token>` and `/reject <token>` for now as fallback paths.

Rationale:

- safer rollout
- useful if callback data breaks or a user forwards/copies the token
- avoids coupling recovery completely to inline keyboard interactions

This fallback can be hidden from normal help later if the button UX proves stable.

## Recommended implementation shape

### 1. Add callback handlers in the Telegram app

In `bot.py`:

- register one or two `CallbackQueryHandler`s for approval actions
- recommended patterns:
  - `^approve:`
  - `^reject:`

### 2. Attach inline keyboard to approval messages

In `chat_handler()`:

- keep calling `create_pending_approval()` exactly as today
- replace the plain text-only reply with:
  - the same explanatory text
  - `reply_markup=InlineKeyboardMarkup(...)`

Suggested callback payloads:

- `approve:<token>`
- `reject:<token>`

This is small enough for Telegram callback data limits and matches the current token format well.

### 3. Add dedicated callback handlers

New handlers in `bot.py`:

- parse `query.data`
- `await query.answer()` immediately
- validate token format defensively
- call existing service methods:
  - `assistant.confirm_approval(...)`
  - `assistant.reject_approval(...)`

### 4. Edit the original message after action

On success:

- edit the original approval message text to show final state
- remove the inline keyboard

Examples:

- `✅ Approved — Added 1 shopping item`
- `❌ Rejected — action cancelled`

On failure:

- answer the callback with a short error
- optionally edit the message if the token is expired or already used

### 5. Keep strict chat/user scoping

Do not trust the button click alone.

The callback handler must still use:

- `chat_id`
- `user_id`
- `token`

and rely on the existing service-layer checks so another user cannot approve someone else’s action.

## File-level plan

### `src/personal_assistant_bot/bot.py`

Planned changes:

- import:
  - `InlineKeyboardButton`
  - `InlineKeyboardMarkup`
  - `CallbackQueryHandler`
- register callback handlers in `build_application()`
- add helper to build approval keyboard
- add `approval_callback_handler()` or split confirm/reject callback handlers
- update `chat_handler()` to send inline buttons for proposed actions
- optionally update help text to say approvals can be done by button

### `src/personal_assistant_bot/services.py`

Likely minimal or no logic changes needed.

Possible additions only if useful:

- helper for formatting approval result text consistently
- optional helper for detecting expired/already-consumed approvals in a friendlier way

### `README.md`

Update user-facing docs:

- approvals happen through inline buttons
- `/confirm` and `/reject` remain as fallback

### Tests

Add coverage for:

- approval message uses inline buttons
- callback confirm path calls the same approval service flow
- callback reject path calls the same rejection service flow
- expired/already-used token behavior from button presses
- callback from wrong chat/user is still rejected by service layer

## UX details to preserve

### Button labels

Recommended labels:

- `Confirm`
- `Deny`

These are clearer than `Approve`/`Reject` in casual personal-assistant use.

### Message behavior after click

Preferred behavior:

- successful click edits the original message
- keyboard disappears
- result is visible in the same place

This avoids message spam and makes it obvious the token has been consumed.

### Duplicate clicks

Expected scenario:

- user taps twice
- Telegram retries
- message already edited

Handler should stay idempotent enough to respond cleanly:

- answer callback
- if already processed, show a short “already handled” result rather than crashing

## Risks and mitigations

### Risk: callback data is forged or tampered with

Mitigation:

- do not trust `query.data`
- parse carefully
- rely on existing `chat_id` + `user_id` + `token` checks in the service layer

### Risk: keyboard becomes stale after restart or expiry

Mitigation:

- when pressed, handler should surface “expired” / “already processed” clearly
- keep `/confirm` and `/reject` fallback during rollout

### Risk: duplicated logic between command approval and button approval

Mitigation:

- button handler should call the same service methods as the slash commands
- keep all approval state transitions in `services.py`

## Validation plan

Implementation should be considered complete when:

1. AI-proposed actions send an inline keyboard
2. clicking `Confirm` executes the same approval path as `/confirm`
3. clicking `Deny` executes the same rejection path as `/reject`
4. the original approval message is edited to final state
5. expired/already-used tokens fail gracefully
6. slash fallback still works
7. tests pass

## Recommended rollout

### Phase 1

- add buttons
- keep slash commands fully documented as fallback

### Phase 2

- once stable, reduce emphasis on `/confirm` and `/reject` in help text
- optionally keep them as hidden recovery commands only

## Final recommendation

Implement inline buttons as the primary approval UX now.

This is a low-risk, high-UX improvement because the hard parts already exist:

- token generation
- safe approval transitions
- chat/user scoping

The work is mostly in Telegram UI wiring, not business logic redesign.
