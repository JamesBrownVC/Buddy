"""ring_tools — let the planner reach James on its own initiative.

Attached to the planner's Hermes profile. Two ways to reach him, in
escalating order of intrusiveness:
  telegram_note(message)  -> a short written nudge in his Telegram
  ring_user(reason)       -> Hermes actually RINGS him (Telegram message with
                             a tap-to-answer live voice call link)

The planner's persona carries the discipline rules (max calls/day, quiet
hours, don't repeat yourself); these tools are deliberately dumb pipes.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

_env_file = Path(__file__).resolve().parents[1] / ".env"
for _line in (_env_file.read_text(encoding="utf-8") if _env_file.exists() else "").splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _key, _, _value = _line.partition("=")
        os.environ.setdefault(_key.strip(), _value.strip())

HUB = os.getenv("HERMES_HUB", "http://127.0.0.1:8484").rstrip("/")
HUB_HEADERS = ({"X-Hermes-Secret": os.getenv("HUB_SECRET", "")}
               if os.getenv("HUB_SECRET", "") else {})

mcp = FastMCP("ring_tools")


@mcp.tool()
def telegram_note(message: str) -> str:
    """Send James a short written Telegram note (a nudge, a reminder, a
    question). Less intrusive than a call — prefer this for small check-ins."""
    try:
        r = httpx.post(f"{HUB}/notify_telegram", headers=HUB_HEADERS,
                       json={"message": message}, timeout=15)
        return "note sent" if r.status_code == 200 else f"failed: {r.text[:120]}"
    except Exception as e:
        return f"could not send note: {e}"


@mcp.tool()
def ring_user(reason: str) -> str:
    """RING James for a live voice check-in: he gets a Telegram message with a
    tap-to-answer call link, and the voice agent opens the call with your
    reason as context. Use sparingly — a call interrupts him. After ringing,
    save to memory THAT you rang, WHEN, and WHY, so you never spam."""
    try:
        r = httpx.post(f"{HUB}/webhook/ring", headers=HUB_HEADERS,
                       json={"nudge": reason, "source": "planner"}, timeout=20)
        return ("ringing James now" if r.status_code == 200
                else f"ring failed: {r.text[:120]}")
    except Exception as e:
        return f"could not ring: {e}"


if __name__ == "__main__":
    mcp.run()
