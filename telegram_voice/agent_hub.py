"""Agent hub — the modular backend the ElevenLabs voice agent talks to.

ElevenLabs is only the mouth/ears: during a live call it invokes these
endpoints as webhook "server tools", so the intelligence stays here and
each capability is swappable.

Endpoints (each = one tool in the ElevenLabs dashboard):
  POST /screen_context   what is the user doing right now (active window)
  POST /remember         {"fact": "..."}       persist something Hermes learned
  POST /recall           {"query": "..."}      recent memory for this user
  POST /log_win          {"what": "..."}       user completed a step — log it
  POST /think            {"question": "..."}   hand a hard question to the brain
  POST /notify_telegram  {"message": "..."}    drop a note in the Telegram thread
  POST /post_call        ElevenLabs post-call webhook -> transcript to memory
                          + spoken Telegram summary

Run:   .venv\\Scripts\\python.exe -m uvicorn agent_hub:app --port 8484
Expose: ngrok http 8484   (or: cloudflared tunnel --url http://localhost:8484)
then use https://<tunnel>/<endpoint> as each tool's URL in the dashboard.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os

import config  # first: applies the Windows SSL cert-store fix

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from brain import think as brain_think

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hub")

app = FastAPI(title="Hermes agent hub")

HUB_SECRET = os.getenv("HUB_SECRET", "")
PUBLIC_PATHS = {"/answer", "/health", "/post_call", "/docs", "/openapi.json"}
SUBSCRIBERS_FILE = None  # set below after STATE_DIR


@app.middleware("http")
async def _auth(request: Request, call_next):
    """Shared-secret auth for everything except the public pages.
    ElevenLabs tools and remote agents send X-Hermes-Secret."""
    if HUB_SECRET and request.url.path not in PUBLIC_PATHS:
        if request.headers.get("x-hermes-secret") != HUB_SECRET:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)

MEMORY_FILE = config.STATE_DIR / "memory.md"
WINS_FILE = config.STATE_DIR / "wins.md"
TRANSCRIPTS = config.STATE_DIR / "transcripts"
TRANSCRIPTS.mkdir(exist_ok=True)
SUBSCRIBERS_FILE = config.STATE_DIR / "subscribers.json"
EVENTS_LOG = config.STATE_DIR / "events.jsonl"


def _subscribers() -> list[str]:
    if SUBSCRIBERS_FILE.exists():
        return json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
    return []


async def broadcast(event_type: str, data: dict) -> None:
    """Fan an event out to every subscribed remote agent (fire-and-forget).
    This is the outbound half of the communication stream."""
    event = {"type": event_type, "ts": _now(), "data": data}
    with open(EVENTS_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    subs = _subscribers()
    if not subs:
        return
    async with httpx.AsyncClient(timeout=5) as c:
        for url in subs:
            try:
                await c.post(url, json=event,
                             headers={"X-Hermes-Secret": HUB_SECRET})
            except Exception as e:
                log.warning("subscriber %s unreachable: %s", url, e)


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


class Fact(BaseModel):
    fact: str

class Query(BaseModel):
    query: str = ""

class Win(BaseModel):
    what: str

class Question(BaseModel):
    question: str

class Note(BaseModel):
    message: str


@app.post("/screen_context")
def screen_context() -> dict:
    """Active-window snapshot — the cheapest 'follow-along' signal."""
    try:
        import pygetwindow as gw
        active = gw.getActiveWindow()
        title = active.title if active else ""
        others = [t for t in gw.getAllTitles() if t.strip()][:12]
        return {"active_window": title, "open_windows": others}
    except Exception as e:  # never break a live call over a sensor
        return {"active_window": "", "open_windows": [], "error": str(e)}


@app.post("/remember")
def remember(f: Fact) -> dict:
    with open(MEMORY_FILE, "a", encoding="utf-8") as fh:
        fh.write(f"- [{_now()}] {f.fact}\n")
    log.info("remember: %s", f.fact)
    return {"ok": True}


@app.post("/recall")
def recall(q: Query) -> dict:
    if not MEMORY_FILE.exists():
        return {"memories": []}
    lines = MEMORY_FILE.read_text(encoding="utf-8").strip().splitlines()
    if q.query:
        hits = [l for l in lines if any(w.lower() in l.lower() for w in q.query.split())]
        lines = hits or lines
    return {"memories": lines[-15:]}


@app.post("/log_win")
def log_win(w: Win) -> dict:
    with open(WINS_FILE, "a", encoding="utf-8") as fh:
        fh.write(f"- [{_now()}] {w.what}\n")
    return {"ok": True, "streak_note": "logged — mention the win briefly"}


@app.post("/think")
def think(q: Question) -> dict:
    return {"answer": brain_think(q.question)}


@app.post("/notify_telegram")
async def notify_telegram(n: Note) -> dict:
    from telegram import Bot
    chat_id = config.get_chat_id()
    if not (config.BOT_TOKEN and chat_id):
        return {"ok": False, "error": "telegram not configured"}
    async with Bot(config.BOT_TOKEN) as bot:
        await bot.send_message(chat_id=chat_id, text=n.message)
    return {"ok": True}


@app.post("/post_call")
async def post_call(request: Request) -> dict:
    """ElevenLabs post-call webhook: archive transcript, note the gist."""
    payload = await request.json()
    conv_id = payload.get("data", {}).get("conversation_id", "unknown")
    (TRANSCRIPTS / f"{conv_id}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = (payload.get("data", {}).get("analysis", {}) or {}).get(
        "transcript_summary", ""
    )
    if summary:
        with open(MEMORY_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"- [{_now()}] call summary: {summary}\n")
    log.info("post_call archived %s", conv_id)
    await broadcast("call_ended", {"conversation_id": conv_id, "summary": summary})
    return {"ok": True}


class AgentAsk(BaseModel):
    agent: str
    message: str


@app.post("/agents/list")
def agents_list() -> dict:
    from agents_registry import list_agents
    return {"agents": list_agents()}


@app.post("/agents/ask")
async def agents_ask(a: AgentAsk) -> dict:
    import anyio

    from agents_registry import ask_agent
    log.info("agent-exchange -> %s: %s", a.agent, a.message[:120])
    reply = await anyio.to_thread.run_sync(ask_agent, a.agent, a.message)
    log.info("agent-exchange <- %s: %s", a.agent, reply[:120])
    with open(config.STATE_DIR / "agent_exchanges.log", "a", encoding="utf-8") as fh:
        fh.write(f"[{_now()}] hermes->{a.agent}: {a.message}\n"
                 f"[{_now()}] {a.agent}->hermes: {reply}\n")
    await broadcast("agent_exchange",
                    {"to": a.agent, "message": a.message, "reply": reply})
    return {"reply": reply}


# ── Inbound webhooks: remote agents (VPS / Mac mini) drive Hermes ──────

class RingReq(BaseModel):
    nudge: str = ""
    source: str = "remote-agent"

class Event(BaseModel):
    type: str
    data: dict = {}
    source: str = "remote-agent"

class Subscribe(BaseModel):
    url: str


@app.post("/webhook/ring")
async def webhook_ring(r: RingReq) -> dict:
    """A remote agent decides the user needs a call -> Hermes rings them."""
    from call_live import ring
    log.info("webhook_ring from %s: %s", r.source, r.nudge[:120])
    await ring(r.nudge)
    await broadcast("ring", {"nudge": r.nudge, "source": r.source})
    return {"ok": True, "rang": True}


@app.post("/webhook/event")
async def webhook_event(e: Event) -> dict:
    """Generic inbound event from a remote agent: logged + fanned out to
    all other subscribers (the shared communication stream)."""
    log.info("event from %s: %s %s", e.source, e.type, str(e.data)[:120])
    await broadcast(e.type, {**e.data, "source": e.source})
    return {"ok": True}


@app.post("/webhook/subscribe")
def webhook_subscribe(s: Subscribe) -> dict:
    """Remote agent registers a callback URL to receive the event stream."""
    subs = _subscribers()
    if s.url not in subs:
        subs.append(s.url)
        SUBSCRIBERS_FILE.write_text(json.dumps(subs, indent=2), encoding="utf-8")
    log.info("subscriber added: %s", s.url)
    return {"ok": True, "subscribers": len(subs)}


@app.get("/answer", response_class=HTMLResponse)
def answer(nudge: str = "") -> str:
    """Tap-to-answer page: live WebRTC voice call with Hermes, no telephony.
    Hermes 'rings' via Telegram with a link here; ?nudge= is passed to the
    agent as the {{nudge_context}} dynamic variable."""
    agent_id = os.getenv("EL_AGENT_ID", "")
    dyn = json.dumps({"nudge_context": nudge})
    return f"""<!doctype html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes calling…</title>
<style>
 body{{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;
 justify-content:center;background:#0f1117;color:#eee;font-family:system-ui;gap:12px}}
 .pulse{{font-size:64px;animation:p 1.2s infinite}}
 @keyframes p{{50%{{transform:scale(1.15)}}}}
</style></head><body>
<div class="pulse">📞</div>
<h2>Hermes is calling</h2>
<p>Tap the widget below to answer</p>
<elevenlabs-convai agent-id="{agent_id}" dynamic-variables='{dyn}'></elevenlabs-convai>
<script src="https://unpkg.com/@elevenlabs/convai-widget-embed" async></script>
</body></html>"""


@app.get("/health")
def health() -> dict:
    return {"ok": True, "hub": "hermes"}
