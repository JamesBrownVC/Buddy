"""Hermes-initiated 'call': ring the user with a spoken voice note.

Usage:
  .venv\\Scripts\\python.exe call.py "Hey, you said you'd start the report at 3 — ready?"
  .venv\\Scripts\\python.exe call.py            (default nudge)

Works standalone over the Bot HTTP API — the bot.py listener does NOT need
to be running for Hermes to reach out (but run it so your reply is heard).
"""
from __future__ import annotations

import asyncio
import sys

import config  # first: applies the Windows SSL cert-store fix

from telegram import Bot

from tts import synth_ogg

DEFAULT_NUDGE = (
    "Hey, it's Hermes. Quick check-in: what are you on right now? "
    "Send me a voice note back — one sentence is plenty."
)


async def call_user(text: str) -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in telegram_voice/.env")
    chat_id = config.get_chat_id()
    if not chat_id:
        raise SystemExit("No chat id yet — send /start to the bot from Telegram first.")

    bot = Bot(config.BOT_TOKEN)
    ogg = await synth_ogg(text)
    async with bot:
        await bot.send_message(chat_id=chat_id, text="📞 Hermes calling…")
        with open(ogg, "rb") as f:
            await bot.send_voice(chat_id=chat_id, voice=f, caption=text[:1000])
    print("call delivered OK")


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]).strip() or DEFAULT_NUDGE
    asyncio.run(call_user(msg))
