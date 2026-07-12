# Hermes ↔ Telegram voice bridge

Lets the Hermes agent **call you on Telegram**: it speaks with edge-tts and
understands you with **faster-whisper** (CPU int8 — no CUDA, Arc-safe).

> "Whisper Flow": Wispr Flow is a desktop dictation app and can't power a
> Telegram call. This module uses **Whisper (faster-whisper)** for the STT
> half of the call loop instead — same effect, actually wired in.

Two tiers:

| Tier | What it feels like | Reliability |
|---|---|---|
| **A. Voice-note call (default)** | Bot pings "📞 Hermes calling…" + a spoken voice note; you answer with a voice note; it replies out loud | Rock solid — demo with this |
| **B. Real p2p voice call** | Your phone actually rings a Telegram call | Experimental (userbot + pytgcalls) |
| **C. LIVE phone call** | Real phone rings; fully live conversation with barge-in | Needs Twilio number (optional) |
| **D. LIVE tap-to-answer** ⭐ | Telegram ring → tap → live WebRTC voice call, barge-in, all tools | **THE chosen path** — no telephony at all |

## Tier D — the chosen setup (LIVE, no phone number needed)

Hermes rings you on Telegram; tapping the link opens a live voice call with
the ElevenLabs agent (WebRTC — streaming STT/TTS/barge-in) which drives the
modular tools on agent_hub.py.

```
start_all.bat                     # hub + tunnel + telegram bot, self-heals URLs
.venv\Scripts\python.exe call_live.py "you said 3pm was report time"
.venv\Scripts\python.exe watcher.py    # proactive: rings you when you drift
```

`watcher.py` demo mode: `set DRIFT_MINUTES=1` then open YouTube and wait.
Do NOT run start_all.bat while an existing hub/bot instance is running
(port + Telegram polling conflicts) — it's the after-reboot command.

Everything runs from the bundled venv: `telegram_voice\.venv\Scripts\python.exe`.

## Setup (Tier A — 3 minutes)

1. Telegram → **@BotFather** → `/newbot` → copy the token.
2. Put it in `telegram_voice\.env` → `TELEGRAM_BOT_TOKEN=...`
3. Start the listener:
   ```
   cd "hermes-adhd-bridge\telegram_voice"
   .venv\Scripts\python.exe bot.py
   ```
4. In Telegram, send **/start** to your bot (captures your chat id automatically).

## Use

```bat
:: Hermes reaches out (works even without bot.py running):
.venv\Scripts\python.exe call.py "Hey, you said 3pm was report time. Ready?"

:: The full loop: run bot.py, then send it a VOICE NOTE from your phone —
:: it transcribes (Whisper), thinks (brain.py), and replies with a spoken note.
```

### The brain
`brain.py` picks, in order: `BRAIN_CMD` from `.env` → the `claude` CLI
(`claude -p`) → a built-in body-double reply. Point `BRAIN_CMD` at Hermes's
own reasoning endpoint to make it Hermes-native, e.g.
`BRAIN_CMD=curl -s http://localhost:8080/think -d "{text}"`. Commands are
parsed as argument arrays; shell operators such as pipes are intentionally not executed.

### Proactive nudges
`call.py` is a one-shot CLI, so any scheduler works:
`schtasks`, a Python loop, or Hermes's own trigger — just shell out to
`call.py "<message>"` when the screen-context watcher decides you've drifted.

## Tier B — real Telegram calls (experimental)

Bots can't place calls (Bot API limitation), so this uses a **user account**
as the agent via Telethon + pytgcalls/ntgcalls (already installed in the venv).

1. https://my.telegram.org → *API development tools* → create an app →
   put `TG_API_ID` / `TG_API_HASH` in `.env`.
2. Set `CALL_TARGET=@your_username` in `.env`.
3. Best with a **second Telegram account** for the agent (spare SIM/Fragment).
   Using your own account = the agent "calls you from yourself" (works but weird,
   and heavy automation on your main account risks flags).
4. First run logs the agent account in interactively, then it's unattended:
   ```
   .venv\Scripts\python.exe call_real.py "Time to start. I'll stay on the line."
   ```

## Tier C — LIVE phone call (ElevenLabs Agents + Twilio) ⭐

The fully-live path: streaming STT + TTS + turn-taking + interruptions all
handled by ElevenLabs; Twilio carries the actual phone call.

1. **ElevenLabs** (elevenlabs.io) → Agents → New agent "Hermes" → paste the
   system prompt from `HERMES_AGENT_PROMPT.md`, set the first message, pick a
   voice. In the agent's **Security** tab enable *First message* and *System
   prompt* **overrides** (lets call_phone.py inject per-call context).
   Copy the **agent id**.
2. **Twilio** (twilio.com) → free trial → buy a trial number. Trial accounts
   can only call **verified** numbers → verify your own phone. Copy
   **Account SID** and **Auth Token**.
3. ElevenLabs → **Phone Numbers** → *Import from Twilio* (number + SID +
   token) → assign the Hermes agent → copy the **phone number id**.
4. ElevenLabs profile → **API key**.
5. Fill `.env`: `ELEVENLABS_API_KEY`, `EL_AGENT_ID`, `EL_PHONE_NUMBER_ID`,
   `MY_PHONE_NUMBER` (E.164, e.g. +32470123456).
6. Ring yourself:
   ```
   .venv\Scripts\python.exe call_phone.py "You said 3pm was report time — ready?"
   ```

## Modular agents behind the voice (agent_hub.py)

The ElevenLabs agent is only the mouth/ears — mid-call it invokes webhook
tools on `agent_hub.py` (screen context, memory, brain, Telegram, win log),
so every capability is a swappable module. Full wiring guide + demo flow:
**`TOOLS_SETUP.md`**.

```
.venv\Scripts\python.exe -m uvicorn agent_hub:app --host 127.0.0.1 --port 8484
# Public tunnels are disabled by default. Follow ../SECURITY.md before opting in.
```

## Network agent modules (net_agents/)

Each agent = one self-contained file + its own process; the only coupling
is text exchange through the hub.

**Personal context convention**: every agent has its own markdown file at
`net_agents/context/<name>.md`, loaded at startup and prepended to every
LLM call that agent makes. Edit the .md, restart the agent — no code
changes. `@include <path>` lines pull in bigger shared docs (the browser
agent's context includes `BROWSER_ASSISTANT_OPERATIONS.md` from the
project root this way). The ElevenLabs voice prompts (hermes-voice,
planner, memory-coach) come from the same folder via `setup_elevenlabs.py`.

Currently:

- **bookkeeper** (:9102) — the network's memory. Working memory with a
  bell-curve attention window (±3 weeks around today, σ=7d), long-term
  memory that only releases items when completed or passed-undeferred,
  nightly **dreams** at 03:30 (or `POST /dream`) that keep/drop/promote and
  can commission research from the browser agent. Subscribes to the event
  stream, so every call summary is scanned for things worth remembering.
  Uses `BOOKKEEPER_MODEL` (default gpt-4o — mini fumbles dates/op discipline).
- **browser** (:9103) — keyless DuckDuckGo lookup + gpt-4o-mini condensing,
  answers with sources.

Both are in the registry, so the voice agent reaches them mid-call via
`ask_agent`, and they reach each other the same way (dream → browser).

## Files

- `bot.py` — always-on listener: voice note → Whisper → brain → spoken reply
- `call.py` — Hermes-initiated voice-note "call"
- `call_phone.py` — LIVE phone call trigger (ElevenLabs + Twilio)
- `agent_hub.py` — FastAPI hub of modular agent tools the voice agent calls
- `call_real.py` — experimental real p2p call (userbot)
- `tts.py` / `stt.py` / `brain.py` — speak / hear / think, each testable solo
- `config.py` — .env loading + Windows SSL cert-store bugfix (import it first)
- `state/` — captured chat id, audio scratch, userbot session

## Troubleshooting

- **`ASN1: NOT_ENOUGH_DATA` SSL error**: a malformed cert in your Windows cert
  store; `config.py` patches it (falls back to certifi). Import `config` before
  `edge_tts`/`aiohttp`.
- **Whisper slow**: set `WHISPER_MODEL=base` in `.env` (small = better accuracy).
- **edge-tts needs internet.** Fully-offline alternative: swap `tts.py` to
  Kokoro-82M (see `research/03_realtime_voice_ambient_repos.md`).
