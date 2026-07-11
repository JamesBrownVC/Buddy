"""EXPERIMENTAL — place a REAL Telegram voice call (phone rings, you answer).

Telegram bots cannot place calls, so this uses a *user account* (the agent's
own Telegram identity) via Telethon MTProto + pytgcalls/ntgcalls, which
supports private one-to-one calls as of pytgcalls 2.x.

Setup (see README):
  1. .env needs TG_API_ID, TG_API_HASH (from https://my.telegram.org)
     and CALL_TARGET (your @username or numeric id).
  2. First run asks for the AGENT account's phone + login code, then saves
     a session file so later runs are unattended.

Usage:
  .venv\\Scripts\\python.exe call_real.py "Hey, time to start the report."
"""
from __future__ import annotations

import asyncio
import sys

import config
from tts import synth_wav_48k

NUDGE = "Hey, it's Hermes calling. Ready to start? Let's do the first two minutes together."


async def main(text: str) -> None:
    if not (config.TG_API_ID and config.TG_API_HASH and config.CALL_TARGET):
        raise SystemExit("Set TG_API_ID, TG_API_HASH, CALL_TARGET in .env (see README)")

    from telethon import TelegramClient
    from pytgcalls import PyTgCalls
    from pytgcalls.types import MediaStream

    wav = await synth_wav_48k(text)

    client = TelegramClient(
        str(config.STATE_DIR / "hermes_agent"),
        int(config.TG_API_ID),
        config.TG_API_HASH,
    )
    await client.start()  # first run: interactive phone + code login
    calls = PyTgCalls(client)
    await calls.start()

    target = config.CALL_TARGET
    entity = await client.get_entity(int(target) if target.lstrip("-").isdigit() else target)

    print(f"Ringing {getattr(entity, 'username', entity.id)}…")
    await calls.play(entity.id, MediaStream(str(wav), video_flags=MediaStream.Flags.IGNORE))

    # keep the call alive while audio plays (+ a little tail)
    await asyncio.sleep(60)
    try:
        await calls.leave_call(entity.id)
    except Exception:
        pass
    await client.disconnect()
    print("call ended OK")


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]).strip() or NUDGE))
