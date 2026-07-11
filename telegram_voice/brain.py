"""The 'brain' that turns a user transcript into Hermes's reply.

Resolution order:
1. BRAIN_CMD from .env (shell command; {text} is replaced with the transcript)
2. `claude -p` CLI if installed (Claude Code as the brain)
3. Built-in canned body-double reply (never fails, demo-safe)
"""
from __future__ import annotations

import shutil
import subprocess

from config import BRAIN_CMD

HERMES_STYLE = (
    "You are Hermes, a warm, concise ADHD body-double voice companion. "
    "The user said this over a voice call. Reply in 1-3 short spoken-style "
    "sentences: acknowledge, then one concrete next micro-step. No lists, "
    "no markdown — this will be read aloud. User said: "
)


def _run(cmd: str | list[str], shell: bool = False) -> str | None:
    try:
        out = subprocess.run(
            cmd, shell=shell, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        reply = (out.stdout or "").strip()
        if not reply or "API Error" in reply or "Failed to authenticate" in reply:
            return None
        return reply
    except Exception:
        return None


def _find_claude() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    import os
    known = os.path.expanduser(r"~\.local\bin\claude.exe")
    return known if os.path.exists(known) else None


def _openai(style: str, text: str) -> str | None:
    import os

    import httpx
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return None
    try:
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                  "temperature": 0.5, "max_tokens": 300,
                  "messages": [{"role": "system", "content": style},
                               {"role": "user", "content": text}]},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def think(text: str, persona: str = "") -> str:
    style = persona or HERMES_STYLE
    if BRAIN_CMD:
        reply = _run(BRAIN_CMD.replace("{text}", text.replace('"', "'")), shell=True)
        if reply:
            return reply

    reply = _openai(style, text)
    if reply:
        return reply

    claude = _find_claude()
    if claude:
        reply = _run([claude, "-p", f"{style}\n\n{text}"])
        if reply:
            return reply

    return (
        f"Got it — I heard: {text[:120]}. "
        "Let's pick the smallest first step and do just that. "
        "I'm right here with you; tell me when it's done."
    )


if __name__ == "__main__":
    import sys
    print(think(" ".join(sys.argv[1:]) or "I can't get started on my report."))
