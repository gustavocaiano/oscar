# task-and-shopping-management Specification

## Purpose
TBD - created by archiving change telegram-personal-assistant. Update Purpose after archive.
## Requirements
### Requirement: Assistant provides grouped command namespaces for tasks and shopping
The system SHALL expose organized slash commands for structured personal lists, including task-prefixed and shopping-prefixed commands.

#### Scenario: User asks for list-management commands
- **WHEN** the user requests help or command guidance
- **THEN** the assistant shows task and shopping commands under clear feature groupings

### Requirement: User can manage personal tasks
The system SHALL allow the user to create, list, update, and complete tasks through deterministic Telegram commands.

#### Scenario: User adds and completes a task
- **WHEN** the user creates a task and later marks it complete through the task command set
- **THEN** the task is stored persistently
- **THEN** the task status changes are reflected in later task listings and briefings

### Requirement: User can manage shopping items
The system SHALL allow the user to add, list, update, and mark shopping items as bought through deterministic Telegram commands.

#### Scenario: User adds shopping items
- **WHEN** the user sends a shopping add command with one or more items
- **THEN** the assistant stores those items in the shopping list
- **THEN** later shopping list commands show the saved items until they are marked bought or removed

### Requirement: Tasks and shopping items are visible to AI summaries
The system SHALL make stored tasks and shopping items available to assistant briefings and AI chat read operations.

#### Scenario: User asks what is pending
- **WHEN** the user asks the assistant what is still pending or what they need to buy
- **THEN** the assistant includes open tasks and active shopping items in the response

