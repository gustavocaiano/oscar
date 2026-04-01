## ADDED Requirements

### Requirement: Assistant enforces resource-aware transcription limits
The system SHALL enforce configured limits for local transcription, including maximum supported voice-note duration or file size and bounded transcription concurrency.

#### Scenario: Voice note exceeds configured limits
- **WHEN** a received voice note exceeds the configured duration or file-size limits
- **THEN** the assistant rejects the transcription request
- **THEN** the assistant explains that the voice note is too large or too long for the current server limits

#### Scenario: Another transcription is already in progress
- **WHEN** the server is already processing a local transcription and concurrency is limited
- **THEN** the assistant serializes or rejects additional transcription work according to the configured safety behavior

### Requirement: Assistant cleans up temporary audio artifacts
The system SHALL use temporary local storage for downloaded or normalized voice-note files and MUST remove those temporary files after processing finishes or fails.

#### Scenario: Transcription finishes successfully
- **WHEN** local transcription completes successfully
- **THEN** the assistant removes temporary audio artifacts created for that transcription job

#### Scenario: Transcription fails partway through processing
- **WHEN** local transcription fails after temporary files have been created
- **THEN** the assistant still removes temporary audio artifacts associated with the failed attempt

### Requirement: Assistant remains operable when speech-to-text is disabled or unavailable
The system SHALL continue to serve non-voice assistant functionality even when the local speech-to-text feature is disabled or unavailable.

#### Scenario: Speech-to-text is disabled or not configured
- **WHEN** the application is started without a usable local speech-to-text configuration
- **THEN** typed assistant features continue to work normally
- **THEN** voice-note interactions return a clear message indicating that local transcription is unavailable
