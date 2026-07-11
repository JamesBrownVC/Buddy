"""Hermes Telegram voice bridge — the always-on listener.

Run:  .venv\\Scripts\\python.exe bot.py

- /start        captures your chat id (do this once from your phone)
- voice note    -> faster-whisper transcript -> brain -> voice-note reply
- text message  -> brain -> voice-note reply
Hermes can *initiate* contact any time via call.py (see README).
"""
from __future__ import annotations

import logging

import config  # first: applies the Windows SSL cert-store fix

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters,
)

from brain import think
from stt import transcribe
from tts import synth_ogg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hermes")


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    config.save_chat_id(chat_id)
    log.info("Captured chat_id=%s", chat_id)
    await update.message.reply_text(
        "Hermes here. I've got your number.\n"
        "• /call — start a live voice call with me\n"
        "• or send a voice note / text and I'll answer out loud."
    )


async def cmd_call(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """User-initiated live call: /call [optional topic]."""
    import os
    import urllib.parse
    config.save_chat_id(update.effective_chat.id)
    hub = os.getenv("HUB_PUBLIC_URL", "").rstrip("/")
    if not hub:
        await update.message.reply_text("Live calls not configured (HUB_PUBLIC_URL).")
        return
    topic = " ".join(update.message.text.split()[1:]).strip()
    url = f"{hub}/answer"
    if topic:
        url += "?nudge=" + urllib.parse.quote(f"The user started this call about: {topic}")
    await update.message.reply_text(
        f"📞 *Live call ready*\n[Tap to talk to Hermes]({url})",
        parse_mode="Markdown",
    )


async def _reply_spoken(update: Update, user_text: str) -> None:
    reply = think(user_text)
    log.info("brain reply: %s", reply[:200])
    ogg = await synth_ogg(reply)
    with open(ogg, "rb") as f:
        await update.message.reply_voice(voice=f, caption=reply[:1000])


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    config.save_chat_id(update.effective_chat.id)
    voice = update.message.voice or update.message.audio
    tg_file = await ctx.bot.get_file(voice.file_id)
    local = config.AUDIO_DIR / f"in_{voice.file_unique_id}.ogg"
    await tg_file.download_to_drive(str(local))

    text = transcribe(local)
    log.info("heard: %s", text)
    if not text:
        await update.message.reply_text("I couldn't make that out — try again?")
        return
    await update.message.reply_text(f"🎧 heard: “{text}”")
    await _reply_spoken(update, text)


async def on_text(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    config.save_chat_id(update.effective_chat.id)
    # if the orchestrator has a task parked waiting on the user, this text
    # answers it (takes priority over the chat brain)
    try:
        import httpx
        r = httpx.post("http://localhost:9104/user_reply",
                       json={"text": update.message.text}, timeout=10)
        if r.status_code == 200 and r.json().get("ok"):
            await update.message.reply_text(
                f"🧭 got it — resuming task {r.json().get('task_id')}")
            return
    except Exception:
        pass
    await _reply_spoken(update, update.message.text)


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in telegram_voice/.env (get it from @BotFather)")
    async def _post_init(a: Application) -> None:
        await a.bot.set_my_commands([
            ("call", "start a live voice call with Hermes"),
            ("start", "(re)connect Hermes to this chat"),
        ])

    app = Application.builder().token(config.BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("call", cmd_call))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Hermes voice bridge polling… send /start to the bot from your phone.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
