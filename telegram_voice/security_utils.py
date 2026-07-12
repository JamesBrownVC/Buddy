"""Security helpers shared by Buddy's hub, launchers, and local clients.

Secrets live in ``telegram_voice/.env`` only.  The public repository contains
no usable credentials; launchers generate a strong HUB_SECRET on first run.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"


def _read_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def ensure_env_secret(name: str = "HUB_SECRET", nbytes: int = 32) -> str:
    """Return an existing secret or create one in the ignored local .env.

    This is intentionally called by the launchers before they spawn children,
    so every local process inherits the same value.
    """
    current = os.getenv(name, "") or _read_env_file().get(name, "")
    if current:
        os.environ[name] = current
        return current

    value = secrets.token_urlsafe(nbytes)
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    text += f"{name}={value}\n"
    ENV_FILE.write_text(text, encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass
    os.environ[name] = value
    return value


def set_env_value(name: str, value: str) -> None:
    """Persist a non-secret runtime setting in the ignored local .env."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    replacement = f"{name}={value}"
    updated = False
    for index, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == name:
            lines[index] = replacement
            updated = True
            break
    if not updated:
        lines.append(replacement)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass
    os.environ[name] = value


def hub_headers() -> dict[str, str]:
    secret = os.getenv("HUB_SECRET", "") or _read_env_file().get("HUB_SECRET", "")
    return {"X-Hermes-Secret": secret} if secret else {}


def sign_answer_link(nudge: str, *, expires: int | None = None) -> tuple[int, str]:
    """Sign a short-lived /answer link without putting a secret in the URL."""
    secret = os.getenv("HUB_SECRET", "") or _read_env_file().get("HUB_SECRET", "")
    if not secret:
        raise RuntimeError("HUB_SECRET is not configured; start Buddy with its launcher")
    exp = expires if expires is not None else int(time.time()) + 10 * 60
    message = f"{exp}\n{nudge}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return exp, signature


def verify_answer_link(nudge: str, expires: int, signature: str) -> bool:
    if expires < int(time.time()) or expires > int(time.time()) + 15 * 60:
        return False
    try:
        _, expected = sign_answer_link(nudge, expires=expires)
    except RuntimeError:
        return False
    return hmac.compare_digest(expected, signature or "")


def verify_elevenlabs_signature(
    body: bytes,
    signature_header: str,
    secret: str,
    *,
    tolerance_seconds: int = 300,
) -> bool:
    """Validate ElevenLabs' ``t=<unix>,v0=<HMAC>`` webhook signature."""
    if not secret or not signature_header:
        return False
    fields: dict[str, list[str]] = {}
    for part in signature_header.split(","):
        key, sep, value = part.strip().partition("=")
        if sep:
            fields.setdefault(key, []).append(value)
    try:
        timestamp = int(fields["t"][0])
    except (KeyError, ValueError, IndexError):
        return False
    if abs(int(time.time()) - timestamp) > tolerance_seconds:
        return False
    signed = str(timestamp).encode("ascii") + b"." + body
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in fields.get("v0", []))
