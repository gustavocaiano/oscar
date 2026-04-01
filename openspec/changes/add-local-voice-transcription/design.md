## Context

The assistant already supports structured slash commands, AI chat for normal text messages, approval-gated writes, SQLite persistence, and optional calendar integration. It currently does not accept spoken input. The desired change is to let the bot receive Telegram voice notes, transcribe them locally on the server, and continue through the assistant workflow without relying on cloud speech APIs or a GPU.

The relevant deployment constraints are known:

- no GPU
- expected hardware tier: 2 vCPU / 4 GB RAM
- initial media scope: Telegram voice notes only
- language scope: Portuguese + English
- resource usage matters more than maximum transcription quality

This means the design must prioritize bounded CPU and memory use, safe temporary-file handling, and predictable latency over large-model accuracy or broad media support.

## Goals / Non-Goals

**Goals:**
- Add local server-side transcription for Telegram voice notes.
- Feed completed transcripts into the same assistant ingestion path used for non-command text.
- Preserve the existing approval model for AI-originated writes.
- Keep resource usage acceptable on a 2 vCPU / 4 GB RAM CPU-only server.
- Add operational limits for duration, file size, concurrency, and cleanup so transcription cannot degrade the entire bot.

**Non-Goals:**
- Supporting arbitrary long audio uploads, podcasts, or meeting recordings in the first version.
- Supporting GPU-accelerated inference.
- Adding cloud speech-to-text services.
- Implementing streaming/live dictation.
- Reworking the full slash-command system so spoken commands map directly to every deterministic command in the first release.

## Decisions

### 1. Use `faster-whisper` as the initial transcription runtime
- **Decision:** Use `faster-whisper` in-process with CPU `int8` inference.
- **Why:** It is the best fit for an existing Python bot, keeps the integration simple, performs better than the reference `openai-whisper` implementation on CPU, and avoids introducing a separate `whisper.cpp` sidecar unless resource pressure proves it necessary.
- **Alternatives considered:**
  - **`whisper.cpp`**: better for extremely small servers, but adds more subprocess/service orchestration and a more complex integration path.
  - **`openai-whisper`**: heavier and slower on CPU with no advantage for this use case.

### 2. Start with the multilingual `base` model on CPU INT8
- **Decision:** Default to multilingual `base` with CPU `int8` compute.
- **Why:** The user needs Portuguese + English, which rules out `.en`-only models. `base` is a better fit than `small` for the initial 2 vCPU / 4 GB target because it reduces latency and memory pressure while staying more useful than `tiny`.
- **Alternatives considered:**
  - **`small` multilingual**: better accuracy, but riskier for latency on the target hardware.
  - **`tiny` multilingual**: lighter, but more error-prone for mixed-language dictation.

### 3. Support Telegram voice notes only in v1
- **Decision:** Add `voice` handling first and defer `audio` files.
- **Why:** Voice notes are the most common dictation path, have tighter usage expectations, and reduce the surface area for oversized or oddly encoded uploads.
- **Alternatives considered:**
  - **Voice + audio together**: more scope and more input variability immediately.

### 4. Route transcripts into a shared non-command text ingestion path
- **Decision:** Extract or introduce a shared text-processing method used by normal typed chat and transcribed voice messages.
- **Why:** This avoids duplicating AI chat logic and ensures approvals, chat history, and future enhancements remain consistent.
- **Alternatives considered:**
  - **Dedicated voice-only AI path**: simpler at first glance, but duplicates behavior.
  - **Full command-router extraction in the same change**: useful later, but more scope than needed for v1.

### 5. Keep v1 transcript routing focused on non-command assistant behavior
- **Decision:** In the initial version, successful voice transcripts will enter the same non-command assistant path as ordinary chat text.
- **Why:** The existing deterministic slash command system is still command-handler-based. Reusing the AI chat path provides immediate value with much less complexity.
- **Alternatives considered:**
  - **Natural-language direct command routing**: valuable later, but needs a separate parser/router design.

### 6. Use strict guardrails for server safety
- **Decision:** Enforce a single transcription at a time, short-duration limits, file-size checks, and immediate temporary-file cleanup.
- **Why:** CPU transcription can easily consume most available server resources on a small VPS if left unconstrained.
- **Alternatives considered:**
  - **Concurrent transcriptions**: not justified for a small personal assistant deployment.
  - **Unlimited audio duration**: too risky on CPU-only infrastructure.

### 7. Keep raw audio ephemeral and store transcript metadata only
- **Decision:** Download voice notes to a temporary location, transcribe, then delete the files immediately. Persist transcript text through existing chat history paths and optionally lightweight transcription metadata if needed later.
- **Why:** This minimizes disk usage, reduces privacy risk, and avoids turning SQLite into media storage.
- **Alternatives considered:**
  - **Store raw audio permanently**: unnecessary for the feature goal and risky for storage/privacy.

## Risks / Trade-offs

- **[CPU latency on a small server]** → Mitigate with `base` multilingual + `int8`, one transcription at a time, and hard duration limits.
- **[Transcription errors in mixed-language speech]** → Mitigate by echoing the recognized transcript before or with the assistant response and allowing normal correction through chat.
- **[Large or malformed audio inputs]** → Mitigate with Telegram voice-only scope, validation, and clear rejection/error messages.
- **[Model download or cold start delays]** → Mitigate with model caching on disk and documented startup/preload behavior.
- **[Future desire for spoken deterministic commands]** → Mitigate by introducing a shared text-ingestion path now, while explicitly leaving command routing expansion for a later change.

## Migration Plan

1. Add transcription configuration and dependency wiring.
2. Implement a local transcriber adapter and temporary audio-file workflow.
3. Add Telegram voice handlers and route transcripts into the shared text ingestion path.
4. Add operational guardrails and cleanup behavior.
5. Validate on CPU with short Portuguese/English voice notes.
6. If resource usage is unacceptable in production, downgrade the model or switch the backend implementation to `whisper.cpp` in a later follow-up change.

## Open Questions

- What exact default duration limit should be used in v1: 30s, 60s, or 90s?
- Should the bot always echo the transcript back, or only when confidence/quality appears uncertain?
- Is lightweight transcription metadata worth persisting initially, or should v1 keep persistence unchanged beyond the transcript entering chat history?
