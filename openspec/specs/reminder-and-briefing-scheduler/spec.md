# reminder-and-briefing-scheduler Specification

## Purpose
TBD - created by archiving change telegram-personal-assistant. Update Purpose after archive.
## Requirements
### Requirement: User can create timed reminders
The system SHALL allow the user to create reminders with a due time and reminder text through deterministic Telegram commands.

#### Scenario: User creates a reminder
- **WHEN** the user creates a reminder through the reminder command set
- **THEN** the reminder is stored persistently with its scheduled trigger time
- **THEN** the assistant later sends the reminder alert at the scheduled time

### Requirement: Assistant sends proactive scheduled messages
The system SHALL support proactive assistant messages including morning briefings, reminder alerts, hour reminders, and evening wrap-ups.

#### Scenario: Morning briefing is enabled
- **WHEN** the configured morning-brief schedule is reached
- **THEN** the assistant sends a summary of the day to the user without requiring a prompt

### Requirement: Briefings can combine multiple data sources
The system SHALL be able to build briefing content from tasks, shopping items, reminders, notes, hour-tracking status, and calendar information.

#### Scenario: Assistant prepares an evening wrap-up
- **WHEN** the configured evening-wrap-up schedule is reached
- **THEN** the assistant can summarize completed and pending items from multiple assistant tools

### Requirement: Proactive behavior is preference-driven
The system SHALL allow proactive message types and schedules to be enabled or disabled independently.

#### Scenario: User disables evening wrap-up
- **WHEN** the user or configuration disables evening wrap-up messages
- **THEN** the assistant stops sending that proactive message type while leaving other enabled schedules active

