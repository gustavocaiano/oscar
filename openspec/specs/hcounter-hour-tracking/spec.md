# hcounter-hour-tracking Specification

## Purpose
TBD - created by archiving change telegram-personal-assistant. Update Purpose after archive.
## Requirements
### Requirement: Assistant provides organized hour-tracking commands
The system SHALL expose hour-tracking commands under a dedicated command namespace, such as `/h-*`, for logging and querying tracked hours.

#### Scenario: User views command help
- **WHEN** the user requests assistant command guidance
- **THEN** hour-tracking commands appear as a grouped feature set separate from other assistant tools

### Requirement: User can log hours using hcounter-compatible parsing behavior
The system SHALL support hour-entry input behavior compatible with the existing `hcounter` assistant so that hour logging remains predictable for the user.

#### Scenario: User logs hours in a supported format
- **WHEN** the user sends a valid hour-tracking command or input in a supported `hcounter` format
- **THEN** the assistant stores the hour entry successfully
- **THEN** the assistant confirms the logged value in a readable format

### Requirement: User can retrieve monthly totals
The system SHALL provide monthly hour totals based on stored hour entries.

#### Scenario: User asks for current month total
- **WHEN** the user requests the current or specified month total through the hour-tracking command set
- **THEN** the assistant calculates the total using stored hour entries
- **THEN** the assistant returns the formatted monthly total

### Requirement: Assistant can proactively remind the user to log hours
The system SHALL support proactive hour-reminder messages for users who enable that feature.

#### Scenario: Hour reminder is enabled
- **WHEN** the configured hour-reminder schedule is reached and the reminder feature is enabled
- **THEN** the assistant sends a message reminding the user to log hours

