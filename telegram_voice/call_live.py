"""Hermes rings you with a LIVE tap-to-answer call — no telephony needed.

Sends a Telegram 'ring' with a link to the hub's /answer page: tapping it
opens a live WebRTC voice conversation with the Hermes agent (barge-in,
streaming, all six hub tools active).

Usage:
  .venv\\Scripts\\python.exe call_live.py
  .venv\\Scripts\\python.exe call_live.py "you said 3pm was report time"
"""
from __future__ import annotations

import asyncio
import os
import sys
import urllib.parse

import config  # first: applies the Windows SSL cert-store fix

from telegram import Bot

HUB_PUBLIC_URL = os.getenv("HUB_PUBLIC_URL", "").rstrip("/")


async def ring(nudge: str) -> None:
    if not HUB_PUBLIC_URL:
        raise SystemExit("Set HUB_PUBLIC_URL in .env (the cloudflared tunnel URL)")
    chat_id = config.get_chat_id()
    if not (config.BOT_TOKEN and chat_id):
        raise SystemExit("Telegram not configured (token + /start first)")

    url = f"{HUB_PUBLIC_URL}/answer"
    if nudge:
        url += "?nudge=" + urllib.parse.quote(nudge)

    async with Bot(config.BOT_TOKEN) as bot:
        await bot.send_message(
            chat_id=chat_id,
            text=f"📞 *Hermes is calling…*\n[Tap to answer]({url})",
            parse_mode="Markdown",
        )
    print("ring sent OK")


if __name__ == "__main__":
    asyncio.run(ring(" ".join(sys.argv[1:]).strip()))
