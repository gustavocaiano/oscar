## ADDED Requirements

### Requirement: Assistant can transcribe Telegram voice notes locally
The system SHALL accept Telegram voice-note messages, transcribe them locally on the server without using a cloud speech-to-text API, and produce transcript text when transcription succeeds.

#### Scenario: Voice note is transcribed successfully
- **WHEN** a user sends a supported Telegram voice note
- **THEN** the assistant downloads the voice note to temporary local storage
- **THEN** the assistant transcribes the audio locally on the server
- **THEN** the assistant obtains a text transcript for further processing

### Requirement: Assistant limits initial scope to voice notes only
The system SHALL support Telegram `voice` messages in the first release and MUST NOT require normal audio-file support to complete the feature.

#### Scenario: User sends a Telegram voice note
- **WHEN** the incoming media is a Telegram voice note
- **THEN** the assistant attempts local transcription according to the configured limits

#### Scenario: User sends unsupported non-voice audio in v1
- **WHEN** the incoming media is not part of the supported voice-note scope
- **THEN** the assistant responds with a clear message that the media type is not yet supported

### Requirement: Assistant handles transcription failure gracefully
The system SHALL return a user-readable error when local transcription cannot complete and MUST NOT leave the user with silent failure.

#### Scenario: Transcription fails
- **WHEN** the assistant cannot complete local transcription for the received voice note
- **THEN** the assistant sends a user-readable failure message to the chat
- **THEN** the assistant does not continue into the normal transcript-processing flow
