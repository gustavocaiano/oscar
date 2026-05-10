## ADDED Requirements

### Requirement: Bible feature group is explicitly configurable
The system SHALL provide a Bible feature group that is disabled by default and only sends Bible prompts when explicitly enabled by configuration.

#### Scenario: Bible feature is disabled
- **WHEN** the Bible feature group is not enabled
- **THEN** the assistant does not send Bible reading prompts
- **THEN** Bible callback actions are rejected with a clear user-facing message

#### Scenario: Bible feature is enabled
- **WHEN** the Bible feature group is enabled with a daily time and Portuguese translation
- **THEN** the assistant includes Bible reading behavior without disabling existing assistant features

### Requirement: Bible experience is Portuguese-only
The system SHALL use Portuguese for Bible prompt text, chapter content, and Bible-related user-facing responses in the MVP.

#### Scenario: Daily Bible prompt is sent
- **WHEN** the assistant sends the Bible reading prompt
- **THEN** the prompt text and inline button labels are in Portuguese

#### Scenario: Chapter is delivered
- **WHEN** the assistant sends a Bible chapter
- **THEN** the scripture content uses the configured Portuguese translation
- **THEN** surrounding labels, summaries, and errors are in Portuguese

### Requirement: Assistant sends one daily Bible reading prompt
The system SHALL send at most one Bible reading prompt per eligible chat per local calendar day after the configured daily Bible time.

#### Scenario: Daily Bible time is reached
- **WHEN** the Bible feature is enabled and the chat local time reaches the configured Bible daily time
- **THEN** the assistant sends a prompt asking whether the user is ready for the next Bible chapter
- **THEN** the prompt includes an inline action to read the chapter

#### Scenario: Prompt already sent today
- **WHEN** a Bible reading prompt has already been sent for the chat on the current local date
- **THEN** the assistant does not send another Bible reading prompt for that date

#### Scenario: Bot was offline for multiple days
- **WHEN** the assistant resumes after missing one or more prior daily Bible times
- **THEN** the assistant only considers the current local date for prompting
- **THEN** the assistant does not send catch-up prompts for missed dates

### Requirement: Chapter delivery is user-initiated
The system SHALL send the next Bible chapter only after the user explicitly chooses the read action or invokes a Bible read command.

#### Scenario: User clicks read action
- **WHEN** the user clicks the Bible prompt's read action
- **THEN** the assistant fetches the next chapter from the user's stored Bible progress
- **THEN** the assistant sends exactly one chapter in response to that action

#### Scenario: User ignores the prompt
- **WHEN** the user does not click the Bible prompt's read action
- **THEN** the assistant does not send the chapter automatically
- **THEN** the assistant does not advance Bible reading progress

#### Scenario: User dismisses the prompt
- **WHEN** the user chooses a dismiss or not-today action
- **THEN** the assistant updates the prompt message to show it was dismissed
- **THEN** the assistant does not send a chapter
- **THEN** the assistant does not advance Bible reading progress

### Requirement: Reading progress advances sequentially
The system SHALL maintain per-chat Bible reading progress and advance sequentially through the canonical Bible order after successful chapter delivery.

#### Scenario: First chapter is requested
- **WHEN** a chat has no existing Bible reading progress and requests a chapter
- **THEN** the assistant treats Genesis chapter 1 as the next chapter

#### Scenario: Chapter is successfully delivered
- **WHEN** the assistant successfully sends the current next chapter
- **THEN** the assistant advances progress to the following chapter

#### Scenario: End of book is reached
- **WHEN** the delivered chapter is the final chapter of its book
- **THEN** the assistant advances progress to chapter 1 of the next canonical book

#### Scenario: End of Bible is reached
- **WHEN** the delivered chapter is the final chapter of Revelation
- **THEN** the assistant records completion and does not wrap to Genesis without an explicit reset or future reading-plan decision

### Requirement: Bible provider errors do not corrupt progress
The system SHALL handle Bible provider failures without advancing reading progress or sending partial/incorrect chapter completion state.

#### Scenario: Provider request fails
- **WHEN** the configured Bible provider cannot return the requested chapter
- **THEN** the assistant sends a clear Portuguese error message
- **THEN** the assistant does not advance Bible reading progress

#### Scenario: Provider returns invalid chapter data
- **WHEN** the configured Bible provider response does not contain usable chapter text
- **THEN** the assistant treats the request as failed
- **THEN** the assistant does not advance Bible reading progress

### Requirement: Chapter messages are safe for Telegram delivery
The system SHALL deliver Bible chapter content in one or more Telegram messages that respect Telegram message length limits.

#### Scenario: Chapter fits in one message
- **WHEN** the formatted Bible chapter is within the safe Telegram message length
- **THEN** the assistant sends it as one message

#### Scenario: Chapter exceeds one message
- **WHEN** the formatted Bible chapter exceeds the safe Telegram message length
- **THEN** the assistant splits the chapter into ordered message chunks
- **THEN** all chunks are sent before reading progress advances

### Requirement: AI resume is a graceful enhancement
The system SHALL use the configured AI backend for a concise Portuguese resume or reflection when available, but Bible chapter delivery MUST still work without AI formatting.

#### Scenario: AI backend is available
- **WHEN** a chapter is fetched and the AI backend is configured
- **THEN** the assistant may include a concise Portuguese resume or reflection with the chapter delivery
- **THEN** the scripture text remains sourced from the Bible provider response

#### Scenario: AI backend is unavailable
- **WHEN** a chapter is fetched and the AI backend is not configured or fails
- **THEN** the assistant sends the provider chapter text with deterministic Portuguese formatting
- **THEN** the assistant does not fail the reading solely because AI formatting is unavailable
