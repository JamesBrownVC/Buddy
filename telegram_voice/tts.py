"""Text -> Telegram-ready voice note (OGG/Opus) via edge-tts + ffmpeg."""
from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path

# config MUST be imported before edge_tts/aiohttp: it patches a Windows
# cert-store SSL bug that otherwise crashes aiohttp at import time.
from config import AUDIO_DIR, TTS_RATE, TTS_VOICE

import edge_tts  # noqa: E402


async def synth_ogg(text: str, voice: str = TTS_VOICE) -> Path:
    """Synthesize `text` and return path to an OGG/Opus file Telegram renders
    as a native voice note (waveform bubble)."""
    stamp = uuid.uuid4().hex[:8]
    mp3 = AUDIO_DIR / f"tts_{stamp}.mp3"
    ogg = AUDIO_DIR / f"tts_{stamp}.ogg"

    communicate = edge_tts.Communicate(text, voice, rate=TTS_RATE)
    await communicate.save(str(mp3))

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
         "-c:a", "libopus", "-b:a", "32k", "-application", "voip", str(ogg)],
        check=True,
    )
    mp3.unlink(missing_ok=True)
    return ogg


def synth_ogg_sync(text: str, voice: str = TTS_VOICE) -> Path:
    return asyncio.run(synth_ogg(text, voice))


async def synth_wav_48k(text: str, voice: str = TTS_VOICE) -> Path:
    """48kHz stereo WAV — the format pytgcalls wants for real calls."""
    ogg = await synth_ogg(text, voice)
    wav = ogg.with_suffix(".wav")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(ogg),
         "-ar", "48000", "-ac", "2", str(wav)],
        check=True,
    )
    return wav


if __name__ == "__main__":
    import sys
    out = synth_ogg_sync(" ".join(sys.argv[1:]) or "Hermes voice check. One, two, three.")
    print(f"OK -> {out}")
