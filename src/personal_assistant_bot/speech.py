from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:  # pragma: no cover - depends on optional dependency at runtime
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover - exercised indirectly via availability checks
    WhisperModel = None  # type: ignore[assignment]


class SpeechToTextError(RuntimeError):
    """Base speech-to-text error."""


class SpeechToTextUnavailableError(SpeechToTextError):
    """Raised when local speech-to-text is disabled or unavailable."""


class SpeechToTextBusyError(SpeechToTextError):
    """Raised when another transcription is already running."""


class SpeechToTextFailedError(SpeechToTextError):
    """Raised when transcription fails."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None = None
    language_probability: float | None = None
    duration_seconds: float | None = None


class LocalSpeechTranscriber:
    def __init__(
        self,
        *,
        enabled: bool,
        model_name: str,
        device: str,
        compute_type: str,
        language: str | None,
        vad_filter: bool,
        model_dir: Path,
    ):
        self.enabled = enabled
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.vad_filter = vad_filter
        self.model_dir = model_dir
        self._model: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self.enabled and WhisperModel is not None

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    def unavailable_message(self) -> str | None:
        if not self.enabled:
            return "Local voice transcription is not enabled for this assistant."
        if WhisperModel is None:
            return "Local voice transcription is unavailable because faster-whisper is not installed."
        return None

    async def transcribe_file(self, audio_path: Path) -> TranscriptionResult:
        unavailable_message = self.unavailable_message()
        if unavailable_message is not None:
            raise SpeechToTextUnavailableError(unavailable_message)
        if self._lock.locked():
            raise SpeechToTextBusyError("Voice transcription is busy right now. Try again in a moment.")

        async with self._lock:
            return await asyncio.to_thread(self._transcribe_file_sync, audio_path)

    def _transcribe_file_sync(self, audio_path: Path) -> TranscriptionResult:
        try:
            model = self._get_model()
            segments, info = model.transcribe(
                str(audio_path),
                beam_size=5,
                language=self.language,
                vad_filter=self.vad_filter,
            )
            segment_list = list(segments)
        except SpeechToTextUnavailableError:
            raise
        except Exception as exc:  # pragma: no cover - depends on native runtime behavior
            raise SpeechToTextFailedError(f"Transcription failed: {exc}") from exc

        transcript_text = " ".join(segment.text.strip() for segment in segment_list if segment.text.strip()).strip()
        if not transcript_text:
            raise SpeechToTextFailedError("Transcription returned no text.")

        return TranscriptionResult(
            text=transcript_text,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", None),
        )

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        if WhisperModel is None:
            raise SpeechToTextUnavailableError(
                "Local voice transcription is unavailable because faster-whisper is not installed."
            )

        self.model_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Loading speech-to-text model '%s' on %s (%s)",
            self.model_name,
            self.device,
            self.compute_type,
        )
        try:
            try:
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=str(self.model_dir),
                )
            except TypeError:
                self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        except Exception as exc:  # pragma: no cover - depends on local runtime/model availability
            raise SpeechToTextUnavailableError(
                f"Local voice transcription could not start with the current model/runtime settings: {exc}"
            ) from exc
        return self._model
