# notes-and-inbox-capture Specification

## Purpose
TBD - created by archiving change telegram-personal-assistant. Update Purpose after archive.
## Requirements
### Requirement: User can capture notes and inbox items
The system SHALL allow the user to save notes, ideas, and inbox items for later retrieval through deterministic Telegram commands.

#### Scenario: User captures an idea
- **WHEN** the user saves a note or inbox item through the note command set
- **THEN** the assistant stores the captured text persistently
- **THEN** the item can be retrieved later

### Requirement: Notes remain searchable and reusable in assistant responses
The system SHALL make captured notes and inbox items available for later lookup and for AI-assisted briefings or recall.

#### Scenario: User asks about a saved note later
- **WHEN** the user asks the assistant to recall a previously captured note or inbox item
- **THEN** the assistant can retrieve the relevant stored content
- **THEN** the user receives a response based on the saved note data

### Requirement: Notes contribute to briefing context
The system SHALL allow saved notes and inbox items to be included in proactive briefings when relevant.

#### Scenario: Morning briefing includes inbox state
- **WHEN** the assistant sends a morning briefing
- **THEN** it may include outstanding inbox items or saved notes that are still relevant to the day

