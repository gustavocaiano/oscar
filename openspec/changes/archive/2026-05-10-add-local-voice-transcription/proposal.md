## Why

The assistant currently works only with typed text, which makes hands-free capture and quick mobile interaction less useful than it could be. Adding local speech-to-text for Telegram voice notes would let the assistant accept spoken input while preserving privacy, avoiding GPU dependence, and staying within the constraints of a small CPU-only server.

## What Changes

- Add support for receiving Telegram voice notes and transcribing them locally on the server before entering the assistant workflow.
- Introduce a local CPU-friendly speech-to-text adapter, optimized for a 2 vCPU / 4 GB RAM environment with no GPU.
- Add strict operational guardrails for audio duration, file size, concurrency, and temporary-file cleanup so transcription does not overwhelm the server.
- Route completed transcripts into the assistant’s normal text processing flow so spoken input can trigger AI chat and existing approval-gated actions.
- Add configuration for model/runtime selection, language behavior, and transcription limits, starting with Portuguese + English voice notes only.

## Capabilities

### New Capabilities
- `local-voice-note-transcription`: Receive Telegram voice notes, transcribe them locally on a CPU-only server, and surface usable transcript results or clear transcription failures.
- `voice-transcript-routing`: Feed successful voice transcripts into the same assistant text-ingestion path used for typed messages, preserving approvals and normal assistant behavior.
- `speech-resource-guardrails`: Enforce resource-aware limits and operational safety around model loading, file handling, concurrency, and cleanup for local transcription.

### Modified Capabilities
- None.

## Impact

- New speech-to-text adapter code and configuration in the Python application.
- New Telegram media handlers and shared text-routing path in the bot layer.
- New runtime dependency for local transcription, with the preferred initial direction being `faster-whisper` on CPU INT8.
- Potential Docker/runtime adjustments for model caching, temporary audio handling, and optional audio decoding support.
- Additional tests and documentation covering voice-note behavior, resource limits, and transcript routing.
