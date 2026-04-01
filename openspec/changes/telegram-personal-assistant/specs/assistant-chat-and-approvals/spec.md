## ADDED Requirements

### Requirement: Non-command messages use AI chat mode
The system SHALL route Telegram text messages without a recognized slash command to the configured AI backend and use the existing assistant context for that user/chat when generating a reply.

#### Scenario: User sends a normal message
- **WHEN** the user sends a text message that is not a recognized command
- **THEN** the assistant sends the conversation plus relevant assistant context to the AI backend
- **THEN** the assistant returns a conversational reply to the same Telegram chat

### Requirement: AI chat can inspect assistant tools
The system SHALL allow AI chat mode to inspect structured assistant data such as tasks, shopping items, reminders, notes, hour logs, and calendar agenda when generating a response.

#### Scenario: User asks for a summary of the day
- **WHEN** the user asks what they have to do or buy today in normal chat
- **THEN** the assistant can read the relevant stored tools and integrations
- **THEN** the response includes information drawn from those sources

### Requirement: AI-proposed writes require explicit confirmation
The system SHALL require explicit user confirmation before executing any data-changing action proposed from AI chat mode.

#### Scenario: AI proposes a write action
- **WHEN** the assistant infers that a normal chat message should create, update, or delete structured data
- **THEN** the assistant does not execute the write immediately
- **THEN** the assistant asks the user to confirm the proposed action before applying it

### Requirement: Confirmed writes are executed through the same tool layer as commands
The system SHALL execute approved AI-originated writes through the same validated domain services used by deterministic slash commands.

#### Scenario: User confirms an AI-proposed task creation
- **WHEN** the user confirms a pending write proposed by AI chat
- **THEN** the assistant executes the action through the underlying structured task service
- **THEN** the created record becomes visible to later commands and AI reads
