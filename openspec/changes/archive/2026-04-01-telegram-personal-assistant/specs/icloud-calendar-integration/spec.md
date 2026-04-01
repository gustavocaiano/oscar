## ADDED Requirements

### Requirement: Assistant can read agenda from iCloud Calendar via CalDAV
The system SHALL support connecting to Apple/iCloud Calendar through CalDAV and reading upcoming events for assistant responses and command output.

#### Scenario: User lists upcoming events
- **WHEN** the user requests their agenda through the calendar command set
- **THEN** the assistant fetches upcoming events from the configured CalDAV calendar source
- **THEN** the assistant returns those events in a readable Telegram response

### Requirement: Assistant can create basic calendar events
The system SHALL allow the user to create basic calendar events in the configured iCloud calendar through deterministic Telegram commands.

#### Scenario: User adds an event
- **WHEN** the user submits a valid calendar add command with event details
- **THEN** the assistant creates the event in the configured calendar
- **THEN** later agenda reads include that event

### Requirement: Calendar integration remains optional
The system SHALL allow the assistant to function without calendar integration if CalDAV credentials are not configured.

#### Scenario: Calendar is not configured
- **WHEN** the assistant starts without valid CalDAV configuration
- **THEN** non-calendar features continue to work
- **THEN** calendar commands return a clear message explaining that calendar integration is not configured
