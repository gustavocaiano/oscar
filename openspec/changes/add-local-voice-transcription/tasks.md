## 1. Transcription foundation

- [x] 1.1 Add configuration and dependency wiring for local speech-to-text, including CPU model/runtime settings and operational limits.
- [x] 1.2 Add a local transcription adapter using `faster-whisper` with multilingual CPU INT8 defaults and model-cache support.
- [x] 1.3 Add temporary-file handling for downloaded Telegram voice notes, including cleanup on success and failure.

## 2. Telegram voice-note handling

- [x] 2.1 Add a Telegram voice-note handler that downloads supported voice messages and validates duration or file-size limits before transcription.
- [x] 2.2 Introduce a shared non-command text-ingestion path so typed chat and successful voice transcripts use the same downstream assistant flow.
- [x] 2.3 Add user-facing transcript feedback and clear error messages for unsupported media, unavailable speech-to-text, or transcription failure.

## 3. Resource and operational guardrails

- [x] 3.1 Enforce bounded transcription concurrency suitable for a 2 vCPU / 4 GB CPU-only server.
- [x] 3.2 Add runtime behavior for disabled or unavailable local speech-to-text so typed assistant features continue working normally.
- [x] 3.3 Add Docker/runtime updates for the local speech-to-text dependency and model-cache persistence.

## 4. Validation and documentation

- [x] 4.1 Add tests for voice-note handling, transcript routing, transcription failure, and limit enforcement.
- [x] 4.2 Add documentation for local speech-to-text setup, model/runtime configuration, and expected server limits.
- [x] 4.3 Validate the feature locally with short Portuguese and English voice notes and confirm transcripts enter the existing approval-gated assistant workflow.
