# Connecting remote agents (VPS / Mac mini) to Hermes

The hub (`agent_hub.py`) is the communication bus. Everything is plain
webhooks + a shared secret header `X-Hermes-Secret` (value = `HUB_SECRET`
in `.env`). Three channels:

## 1. Hermes → remote agent (voice agent asks, mid-call)

Remote agent exposes `POST /ask` receiving `{"message": "...", "from":
"hermes-voice"}` and returning `{"reply": "..."}`. Register it on the hub
in `agents.json`:

```json
"ops": {"type": "http", "url": "http://vps.example.com:9101/ask",
        "description": "ops agent on the VPS"}
```

That's it — Hermes's `ask_agent` tool can now message it during live calls.

## 2. Remote agent → Hermes (drive the user's companion)

| Endpoint | Body | Effect |
|---|---|---|
| `POST {HUB}/webhook/ring` | `{"nudge": "...", "source": "ops"}` | Hermes rings the user (Telegram tap-to-answer live call) with that context |
| `POST {HUB}/webhook/event` | `{"type": "...", "data": {...}, "source": "ops"}` | Publish onto the shared event stream |

`{HUB}` = the tunnel URL (`HUB_PUBLIC_URL` in `.env`) while the hub lives on
the Windows box; later just the VPS's own address.

## 3. Event stream (hub → all subscribers)

Subscribe once: `POST {HUB}/webhook/subscribe {"url": "http://vps:9101/events"}`.
The hub then POSTs every event to you: `agent_exchange` (every mid-call
agent-to-agent message), `ring`, `call_ended` (with transcript summary),
plus anything other agents publish. Also mirrored to `state/events.jsonl`.

## Contract for the WEB-BROWSER agent (teammate's module)

The book-keeper delegates research by POSTing to the browser agent
(`BROWSER_URL` env on the book-keeper, default `http://localhost:9103/ask`):

```json
POST /ask
{"message": "<question>", "from": "bookkeeper",
 "request_id": "ab12cd34", "reply_to": "http://<bookkeeper>/research_result"}
```

Two valid ways to answer:
- **Sync**: respond `{"reply": "<answer text>"}` in the HTTP response.
- **Async** ("come back with info"): respond without a reply, work, then
  `POST {reply_to}` with `{"request_id": "ab12cd34", "answer": "..."}`.

Answered research lands in the book-keeper's working memory dated today and
is announced on the event stream (`research_requested` / `research_answered`).
A reference implementation satisfying the sync contract runs at
`net_agents/browser.py` — swap `BROWSER_URL` when the real module lands.

## Drop-in template

`example_remote_agent.py` implements all three channels in ~40 lines —
copy it to the remote box, set `HERMES_HUB` + `HERMES_SECRET`, run with
uvicorn, add the registry line.

## When the hub itself moves to the VPS/Mac mini

The hub is portable (pure Python + ffmpeg). On a box with a public address
you drop cloudflared entirely: set `HUB_PUBLIC_URL` to the real host, run
`setup_elevenlabs.py https://your-host` once. The only Windows-specific
tool is `check_screen` (pygetwindow) — invert it: run a tiny sensor on the
desktop that POSTs the active window to `/webhook/event` every 15s, and
serve `screen_context` from the last received event.

## The orchestrator (:9104)

`net_agents/orchestrator.py` is the manager of the network: it owns the
organigramme (`GET /org`, backed by `state/orgchart.json` merged with the
live registry) and a task ledger (`GET /tasks`). Any agent reaches it like
any other agent — `POST {HUB}/agents/ask {"agent": "orchestrator",
"message": "..."}` — and an LLM tool-loop routes the request: build
requests enter the pipeline (book-keeper context -> optional browser
research -> one Telegram question to the user if essential info is missing
-> PRD in `net_agents/state/prds/` -> dispatched to the `builder` agent ->
outcome stored with the book-keeper + Telegram update). Durable facts are
always forwarded to the book-keeper; status questions are answered from
the ledger.

User answers reach a parked task via `POST :9104/user_reply {"text": ...}`
or automatically when a Hermes call summary answers the question
(orchestrator subscribes to the event stream). Unanswered questions
auto-resume with stated assumptions after `ORCH_USER_WAIT` (240 s default).

The `builder` registry entry is a brain-persona placeholder — swap it for
`{"type": "http", "url": "http://vps:9105/ask"}` when the real builder
lives on the VPS/Mac mini.
