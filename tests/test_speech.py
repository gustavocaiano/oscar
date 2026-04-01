from __future__ import annotations

from pathlib import Path

import pytest

from personal_assistant_bot import speech
from personal_assistant_bot.speech import LocalSpeechTranscriber, SpeechToTextUnavailableError


def test_transcriber_wraps_model_initialization_errors(monkeypatch, tmp_path: Path) -> None:
    class BrokenModel:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("invalid compute type")

    monkeypatch.setattr(speech, "WhisperModel", BrokenModel)

    transcriber = LocalSpeechTranscriber(
        enabled=True,
        model_name="base",
        device="cpu",
        compute_type="bad-type",
        language=None,
        vad_filter=True,
        model_dir=tmp_path / "models",
    )

    with pytest.raises(SpeechToTextUnavailableError):
        transcriber._get_model()
