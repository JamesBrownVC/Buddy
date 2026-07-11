"""Shared config for the Hermes Telegram voice bridge.

Reads .env in this directory. State (captured chat id) lives in state/.
"""
from __future__ import annotations

import os
import ssl
from pathlib import Path

import certifi
from dotenv import load_dotenv

# Windows fix: a malformed cert in the system store makes
# SSLContext.load_default_certs() raise ASN1 NOT_ENOUGH_DATA (breaks edge-tts).
# Fall back to certifi's bundle when that happens.
_orig_win_store = ssl.SSLContext._load_windows_store_certs

def _safe_win_store(self, storename, purpose):
    try:
        return _orig_win_store(self, storename, purpose)
    except ssl.SSLError:
        self.load_verify_locations(cafile=certifi.where())
        return bytearray()

ssl.SSLContext._load_windows_store_certs = _safe_win_store

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Voice-note voice (edge-tts). Try: en-US-AriaNeural, en-GB-SoniaNeural, en-US-GuyNeural
TTS_VOICE = os.getenv("TTS_VOICE", "en-US-AriaNeural")
TTS_RATE = os.getenv("TTS_RATE", "+8%")  # slightly brisk = engaged body-double energy

# faster-whisper model: tiny/base/small/medium. small is the accuracy sweet spot on CPU.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")

# Optional brain command. {text} is replaced with the user's transcript.
# If unset, we try the `claude` CLI, else a simple built-in reply.
BRAIN_CMD = os.getenv("BRAIN_CMD", "")

# Real-call (userbot) credentials — only needed for call_real.py
TG_API_ID = os.getenv("TG_API_ID", "")
TG_API_HASH = os.getenv("TG_API_HASH", "")
CALL_TARGET = os.getenv("CALL_TARGET", "")  # your @username or numeric user id

STATE_DIR = HERE / "state"
STATE_DIR.mkdir(exist_ok=True)
CHAT_ID_FILE = STATE_DIR / "chat_id.txt"
AUDIO_DIR = STATE_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)


def get_chat_id() -> str:
    """Chat id captured by /start, or TELEGRAM_CHAT_ID from .env."""
    env = os.getenv("TELEGRAM_CHAT_ID", "")
    if env:
        return env
    if CHAT_ID_FILE.exists():
        return CHAT_ID_FILE.read_text().strip()
    return ""


def save_chat_id(chat_id: int | str) -> None:
    CHAT_ID_FILE.write_text(str(chat_id))
