# Wiring the modular agents into the ElevenLabs voice agent

Architecture: **ElevenLabs = mouth/ears only.** Mid-call it invokes webhook
tools on the local agent hub; every capability behind an endpoint is swappable.

```
 phone call ⇄ ElevenLabs agent ⇄ tunnel ⇄ agent_hub.py ⇄ { screen watcher,
                                                            memory, brain,
                                                            Telegram bridge }
```

## Current tunnel URL (changes on each quick-tunnel restart)

    https://radiation-packet-revision-usr.trycloudflare.com

Start order after a reboot:
1. `.venv\Scripts\python.exe -m uvicorn agent_hub:app --port 8484`
2. `cloudflared tunnel --url http://localhost:8484` → grab the new URL →
   update the tool URLs in the dashboard (or set up a named tunnel / ngrok
   static domain once, to stop re-pasting).

## Tools to add (agent → Tools → Add tool → Webhook)

All are **POST**, `Content-Type: application/json`.

### 1. `check_screen`
- URL: `<tunnel>/screen_context` — body: none
- Description: *Call this when you want to know what the user is doing right
  now. Returns their active window and open windows. Use it to ground your
  nudge ("I see the report is already open — nice").*

### 2. `remember`
- URL: `<tunnel>/remember` — body: `fact` (string, required): *the fact to store*
- Description: *Store an important fact the user told you (goals, deadlines,
  what derails them, what worked). Use whenever you learn something durable.*

### 3. `recall`
- URL: `<tunnel>/recall` — body: `query` (string, optional)
- Description: *Look up what you know about the user before advising. Call at
  the start of substantive conversations.*

### 4. `log_win`
- URL: `<tunnel>/log_win` — body: `what` (string, required)
- Description: *Log it when the user completes a step or task. Celebrate briefly.*

### 5. `ask_brain`
- URL: `<tunnel>/think` — body: `question` (string, required)
- Description: *Delegate questions needing deep reasoning or task breakdown to
  the heavy brain. Relay its answer conversationally.*

### 6. `send_telegram`
- URL: `<tunnel>/notify_telegram` — body: `message` (string, required)
- Description: *Send the user a written Telegram note (a plan, a checklist, a
  link) so they have it after the call ends.*

## Post-call webhook (optional but great)

Agents → Settings → Webhooks → post-call webhook →
`<tunnel>/post_call`. Every call transcript is archived to
`state/transcripts/` and the summary is appended to Hermes memory —
so the *next* call starts already knowing what happened in the last one.

## Demo flow that lands

1. Drift to Twitter/Facebook.
2. `call_phone.py "check what I'm doing and be honest"` → phone rings.
3. Hermes calls `check_screen` live → names what it sees → suggests the
   2-minute re-entry step → `send_telegram` drops the step as text →
   `log_win` when you confirm → post-call summary lands in memory.
