"""Voice note -> text via faster-whisper (int8, CPU — no CUDA needed)."""
from __future__ import annotations

from pathlib import Path

from config import WHISPER_MODEL

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def transcribe(audio_path: str | Path) -> str:
    segments, _info = _get_model().transcribe(str(audio_path), vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


if __name__ == "__main__":
    import sys
    print(transcribe(sys.argv[1]))
