## ADDED Requirements

### Requirement: Successful transcripts enter the assistant text ingestion flow
The system SHALL route a successful voice-note transcript into the same assistant text-ingestion flow used for normal non-command text messages.

#### Scenario: Voice note produces transcript text
- **WHEN** the assistant successfully transcribes a user voice note
- **THEN** the transcript is handed to the assistant text-ingestion path
- **THEN** the assistant responds as though the user had typed that transcript as a normal message

### Requirement: Voice transcripts preserve approval-gated assistant behavior
The system SHALL preserve the existing approval requirement for AI-originated writes when the input originated from a voice transcript.

#### Scenario: Voice transcript leads to a proposed write action
- **WHEN** a transcribed voice message causes the assistant to propose a write action
- **THEN** the assistant does not execute the write immediately
- **THEN** the assistant uses the existing approval-gated behavior before applying the action

### Requirement: Assistant can surface the recognized transcript to the user
The system SHALL provide user-visible transcript feedback before or with the downstream assistant response so the user can understand what speech content was recognized.

#### Scenario: Transcript is available
- **WHEN** a voice note has been transcribed successfully
- **THEN** the assistant includes or exposes the recognized transcript in the interaction
- **THEN** the user can see what text will be processed by the assistant
