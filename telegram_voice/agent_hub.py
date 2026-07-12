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
import html
import json
import logging
import os

import config  # first: applies the Windows SSL cert-store fix

import re
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from brain import think as brain_think
from security_utils import verify_answer_link, verify_elevenlabs_signature

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hub")

_docs_enabled = os.getenv("ENABLE_API_DOCS", "").lower() in {"1", "true", "yes"}
app = FastAPI(
    title="Hermes agent hub",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# Browser access is limited to the local dashboard unless explicitly extended.
_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Hermes-Secret"],
)

HUB_SECRET = os.getenv("HUB_SECRET", "")
PUBLIC_PATHS = {
    "/answer",
    "/health",
    "/post_call",
}
SUBSCRIBERS_FILE = None  # set below after STATE_DIR


@app.middleware("http")
async def _auth(request: Request, call_next):
    """Shared-secret auth for everything except the public pages.
    ElevenLabs tools and remote agents send X-Hermes-Secret."""
    if request.url.path not in PUBLIC_PATHS:
        supplied = request.headers.get("x-hermes-secret", "")
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        import secrets as _secrets
        if not HUB_SECRET or not _secrets.compare_digest(supplied, HUB_SECRET):
            return JSONResponse(
                {"detail": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=()"
    if request.url.path != "/health":
        response.headers["Cache-Control"] = "no-store"
    return response

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
    fact: str = Field(min_length=1, max_length=4000)

class Query(BaseModel):
    query: str = Field("", max_length=500)

class Win(BaseModel):
    what: str = Field(min_length=1, max_length=2000)

class Question(BaseModel):
    question: str = Field(min_length=1, max_length=8000)

class Note(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


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
    """Verified ElevenLabs post-call webhook; raw transcript storage is opt-in."""
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > 2_000_000:
        raise HTTPException(status_code=413, detail="payload too large")
    body = await request.body()
    if len(body) > 2_000_000:
        raise HTTPException(status_code=413, detail="payload too large")
    webhook_secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET", "")
    signature = request.headers.get("elevenlabs-signature", "")
    if not verify_elevenlabs_signature(body, signature, webhook_secret):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    if payload.get("type") != "post_call_transcription":
        return {"ok": True, "ignored": True}
    conv_id = payload.get("data", {}).get("conversation_id", "unknown")
    if not isinstance(conv_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", conv_id):
        raise HTTPException(status_code=400, detail="invalid conversation id")
    transcript_file = TRANSCRIPTS / f"{conv_id}.json"
    processed_file = TRANSCRIPTS / f".{conv_id}.processed"
    try:
        processed_file.touch(exist_ok=False)
        already_processed = False
    except FileExistsError:
        already_processed = True
    if os.getenv("STORE_CALL_TRANSCRIPTS", "0").lower() in {"1", "true", "yes"}:
        transcript_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary = (payload.get("data", {}).get("analysis", {}) or {}).get(
        "transcript_summary", ""
    )
    if not isinstance(summary, str):
        summary = ""
    summary = summary[:4000]
    if summary and not already_processed:
        with open(MEMORY_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"- [{_now()}] call summary: {summary}\n")
    if not already_processed:
        log.info("post_call processed %s", conv_id)
        await broadcast("call_ended", {"conversation_id": conv_id, "summary": summary})
    return {"ok": True, "duplicate": already_processed}


class AgentAsk(BaseModel):
    agent: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=16_000)
    # who is asking: another agent's name, or "external" for a top-level task.
    # This turns the exchange log into a task tree (macro task -> sub-tasks).
    from_: str = Field("external", alias="from")

    class Config:
        populate_by_name = True


def _log_task(rec: dict) -> None:
    """Append one audited task record (ask, reply, who asked, timing) so the
    Audit agent can judge each action against its ask — at both the macro
    (external request) and micro (agent->agent) level. Never raises."""
    try:
        with open(config.STATE_DIR / "task_log.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


@app.post("/agents/list")
def agents_list() -> dict:
    from agents_registry import list_agents
    return {"agents": list_agents()}


@app.post("/agents/ask")
async def agents_ask(a: AgentAsk) -> dict:
    import anyio
    import time as _time

    from agents_registry import ask_agent
    asker = (a.from_ or "external").strip().lower()
    level = "macro" if asker == "external" else "micro"
    log.info("agent-exchange %s -> %s: %s", asker, a.agent, a.message[:120])
    t0 = _time.time()
    reply = await anyio.to_thread.run_sync(ask_agent, a.agent, a.message)
    ms = int((_time.time() - t0) * 1000)
    log.info("agent-exchange <- %s (%dms): %s", a.agent, ms, reply[:120])
    _log_task({"ts": _now(), "level": level, "from": asker, "agent": a.agent,
               "ask": a.message[:1000], "reply": (reply or "")[:1500], "ms": ms,
               "ok": bool(reply and reply.strip())})
    with open(config.STATE_DIR / "agent_exchanges.log", "a", encoding="utf-8") as fh:
        fh.write(f"[{_now()}] {asker}->{a.agent}: {a.message}\n"
                 f"[{_now()}] {a.agent}->{asker}: {reply}\n")
    await broadcast("agent_exchange",
                    {"to": a.agent, "from": asker, "message": a.message, "reply": reply})
    return {"reply": reply}


# ── Inbound webhooks: remote agents (VPS / Mac mini) drive Hermes ──────

class RingReq(BaseModel):
    nudge: str = Field("", max_length=1000)
    source: str = Field("remote-agent", max_length=100)

class Event(BaseModel):
    type: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    data: dict = {}
    source: str = Field("remote-agent", max_length=100)

class Subscribe(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


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
def answer(nudge: str = "", expires: int = 0, sig: str = "") -> HTMLResponse:
    """Tap-to-answer page: live WebRTC voice call with Hermes, no telephony.
    Hermes 'rings' via Telegram with a link here; ?nudge= is passed to the
    agent as the {{nudge_context}} dynamic variable."""
    if len(nudge) > 1000 or not verify_answer_link(nudge, expires, sig):
        raise HTTPException(status_code=403, detail="invalid or expired call link")
    agent_id = os.getenv("EL_AGENT_ID", "")
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not agent_id or not api_key:
        raise HTTPException(status_code=503, detail="voice agent is not configured")
    try:
        signed = httpx.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": agent_id},
            headers={"xi-api-key": api_key},
            timeout=15,
        )
        signed.raise_for_status()
        signed_url = signed.json()["signed_url"]
    except Exception as exc:
        log.warning("failed to create ElevenLabs signed URL: %s", exc)
        raise HTTPException(status_code=502, detail="voice session unavailable") from exc
    dyn = html.escape(json.dumps({"nudge_context": nudge}), quote=True)
    signed_attr = html.escape(signed_url, quote=True)
    body = f"""<!doctype html><html><head>
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
<p>You are about to speak with an AI assistant. Voice is processed by ElevenLabs;
Buddy is configured not to retain call audio and to delete hosted conversation data.</p>
<p>Tap the widget below to answer</p>
<elevenlabs-convai signed-url="{signed_attr}" dynamic-variables='{dyn}'></elevenlabs-convai>
<script src="https://unpkg.com/@elevenlabs/convai-widget-embed@0.14.8" async></script>
</body></html>"""
    return HTMLResponse(
        body,
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; script-src https://unpkg.com; "
                "style-src 'unsafe-inline'; connect-src https://api.elevenlabs.io "
                "wss://api.elevenlabs.io; img-src data: https:; media-src blob:"
            )
        },
    )


class ToggleReq(BaseModel):
    id: str
    type: str = "working"


@app.get("/api/dashboard-state")
async def get_dashboard_state():
    # 1. Check agent health in parallel
    agents = {
        "bookkeeper": "http://localhost:9102/health",
        "browser": "http://localhost:9103/health",
        "orchestrator": "http://localhost:9104/health"
    }
    health_status = {}
    async with httpx.AsyncClient(timeout=0.5) as client:
        for name, url in agents.items():
            try:
                res = await client.get(url)
                health_status[name] = "ready" if res.status_code == 200 else "offline"
            except Exception:
                health_status[name] = "offline"

    # 2. Read bookkeeper memory
    working_items = []
    longterm_items = []
    net_state_dir = Path(__file__).resolve().parent / "net_agents" / "state"
    bk_file = net_state_dir / "bookkeeper.json"
    
    if bk_file.exists():
        try:
            bk_data = json.loads(bk_file.read_text(encoding="utf-8"))
            working_items = bk_data.get("working", [])
            longterm_items = bk_data.get("longterm", [])
        except Exception as e:
            log.warning("Failed to parse bookkeeper.json: %s", e)

    # 3. Read orchestrator tasks
    orch_tasks = []
    orch_file = net_state_dir / "orchestrator_tasks.json"
    if orch_file.exists():
        try:
            orch_tasks = json.loads(orch_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to parse orchestrator_tasks.json: %s", e)

    # Find the active task
    active_task = None
    for t in reversed(orch_tasks):
        if t.get("status") not in ("done", "failed"):
            active_task = t
            break

    # 4. Determine focus title and steps
    focus_title = "No active task. Talk to Buddy to start!"
    focus_progress = "0/0"
    steps = []

    if active_task:
        focus_title = active_task.get("request", "")
        # Can we extract steps from the task's builder reply or logs?
        builder_reply = active_task.get("builder_reply", "")
        parsed_steps = []
        if builder_reply:
            lines = builder_reply.splitlines()
            idx = 1
            for line in lines:
                line_str = line.strip()
                match = re.match(r'^(?:\d+[\.\)]|[\-\*])\s*(.*)', line_str)
                if match:
                    step_text = match.group(1).strip()
                    if step_text:
                        parsed_steps.append({
                            "id": f"task-step-{active_task['id']}-{idx}",
                            "index": f"{idx:02d}",
                            "title": step_text,
                            "desc": "Builder task step",
                            "done": False
                        })
                        idx += 1
        if parsed_steps:
            steps = parsed_steps
        else:
            # Fallback to logs
            task_logs = active_task.get("log", [])
            idx = 1
            for l in task_logs[-3:]:
                clean_log = re.sub(r'^\[.*?\]\s*', '', l)
                steps.append({
                    "id": f"task-log-{active_task['id']}-{idx}",
                    "index": f"{idx:02d}",
                    "title": clean_log,
                    "desc": "Task log status",
                    "done": False
                })
                idx += 1
        
        if active_task.get("status") == "done":
            focus_progress = f"{len(steps)}/{len(steps)}"
            for s in steps:
                s["done"] = True
        else:
            focus_progress = f"0/{len(steps)}"
    else:
        # Fallback to bookkeeper working items
        active_working = [i for i in working_items if i.get("status") == "active"]
        if active_working:
            focus_title = "Your current working memory"
            idx = 1
            for item in active_working[:3]:
                steps.append({
                    "id": item["id"],
                    "index": f"{idx:02d}",
                    "title": item["text"],
                    "desc": f"Added on {item.get('created', '')}",
                    "done": item.get("status") == "done"
                })
                idx += 1
            done_count = sum(1 for s in steps if s["done"])
            focus_progress = f"{done_count}/{len(steps)}"
        else:
            focus_title = "Ship the Buddy demo"
            steps = [
                {"id": "mock-1", "index": "01", "title": "Finish the dashboard", "desc": "Buddy is handling the code.", "done": False},
                {"id": "mock-2", "index": "02", "title": "Connect Cloudflare", "desc": "Point Pages at /frontend.", "done": False},
                {"id": "mock-3", "index": "03", "title": "Practice the story", "desc": "Voice → agents → visible action.", "done": False}
            ]
            focus_progress = "0/3"

    # 5. Extract latest browser research action from events.jsonl
    browser_title = "Idle."
    browser_desc = "Waiting for next action."
    browser_status = "idle"
    
    events_log = Path(__file__).resolve().parent / "state" / "events.jsonl"
    if events_log.exists():
        try:
            lines = events_log.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines):
                if not line:
                    continue
                ev = json.loads(line)
                ev_type = ev.get("type")
                ev_data = ev.get("data", {})
                if ev_type == "research_requested":
                    browser_title = ev_data.get("question", "Researching...")
                    browser_desc = "Web browser agent researching query."
                    browser_status = "working"
                    break
                elif ev_type == "research_answered":
                    browser_title = ev_data.get("question", "Research complete.")
                    ans = ev_data.get("answer", "")
                    browser_desc = ans[:150] + "..." if len(ans) > 150 else ans
                    browser_status = "synced"
                    break
                elif ev_type == "agent_exchange" and ev_data.get("to") == "browser":
                    browser_title = ev_data.get("message", "Browsing...")
                    reply = ev_data.get("reply", "")
                    if reply:
                        browser_desc = reply[:150] + "..." if len(reply) > 150 else reply
                        browser_status = "synced"
                    else:
                        browser_desc = "Web browser agent working."
                        browser_status = "working"
                    break
        except Exception as e:
            log.warning("Failed to parse events.jsonl: %s", e)

    # 6. Crew agent statuses
    crew = [
        {"name": "Hermes", "desc": "Keeping the plan small and moving", "state": "ready"},
        {"name": "Browser", "desc": "Researching web contexts", "state": "ready"},
        {"name": "Bookkeeper", "desc": "Capturing facts and schedule", "state": "ready"}
    ]
    for member in crew:
        name_lower = member["name"].lower()
        if name_lower == "hermes":
            member["state"] = "ready"
        elif name_lower in health_status:
            member["state"] = health_status[name_lower]

    # 7. Later tasks
    later_tasks = []
    active_longterm = [i for i in longterm_items if i.get("status") == "active"]
    if active_longterm:
        priorities = ["orange", "blue", "green"]
        for idx, item in enumerate(active_longterm[:3]):
            later_tasks.append({
                "title": item["text"],
                "desc": f"Due: {item.get('date') or 'later'}",
                "time": item.get("date") or "later",
                "priority": priorities[idx % 3]
            })
    else:
        later_tasks = [
            {"title": "Connect live browser feed", "desc": "After the static deploy", "time": "later", "priority": "orange"},
            {"title": "Test Telegram call flow", "desc": "One end-to-end run", "time": "17:00", "priority": "blue"},
            {"title": "Eat something real", "desc": "Non-negotiable", "time": "soon", "priority": "green"}
        ]

    return {
        "system_status": f"Mac mini online · {sum(1 for s in health_status.values() if s == 'ready') + 1} agents ready",
        "focus": {
            "title": focus_title,
            "progress": focus_progress,
            "steps": steps
        },
        "browser": {
            "status": browser_status,
            "title": browser_title,
            "desc": browser_desc,
            "url": "browser.buddy.local · research session"
        },
        "crew": crew,
        "later_tasks": later_tasks,
        "el_agent_id": os.getenv("EL_AGENT_ID", "")
    }


@app.post("/api/toggle-step")
def toggle_step(r: ToggleReq) -> dict:
    net_state_dir = Path(__file__).resolve().parent / "net_agents" / "state"
    bk_file = net_state_dir / "bookkeeper.json"
    orch_file = net_state_dir / "orchestrator_tasks.json"

    # Try toggling in bookkeeper
    if bk_file.exists():
        try:
            bk_data = json.loads(bk_file.read_text(encoding="utf-8"))
            modified = False
            for k in ("working", "longterm"):
                for item in bk_data.get(k, []):
                    if item.get("id") == r.id:
                        item["status"] = "done" if item.get("status") == "active" else "active"
                        modified = True
                        break
            if modified:
                bk_file.write_text(json.dumps(bk_data, indent=2, ensure_ascii=False), encoding="utf-8")
                return {"ok": True, "source": "bookkeeper", "id": r.id}
        except Exception as e:
            log.warning("Failed to modify bookkeeper.json: %s", e)

    # Try toggling in orchestrator tasks
    if orch_file.exists():
        try:
            orch_tasks = json.loads(orch_file.read_text(encoding="utf-8"))
            modified = False
            for task in orch_tasks:
                if task.get("id") == r.id or r.id.startswith(f"task-step-{task['id']}") or r.id.startswith(f"task-log-{task['id']}"):
                    task["status"] = "done" if task.get("status") != "done" else "gathering_context"
                    modified = True
                    break
            if modified:
                orch_file.write_text(json.dumps(orch_tasks, indent=2, ensure_ascii=False), encoding="utf-8")
                return {"ok": True, "source": "orchestrator", "id": r.id}
        except Exception as e:
            log.warning("Failed to modify orchestrator_tasks.json: %s", e)

    # If it's a mock step, we just echo success so the UI updates
    if r.id.startswith("mock-"):
        return {"ok": True, "source": "mock", "id": r.id}

    return {"ok": False, "error": f"Item {r.id} not found."}


# ── Read-only agent documentation for the frontend node-graph ──────────
# Maps friendly node names (as shown in the dashboard graph) to the exact
# markdown file that documents that agent.
CONTEXT_DIR = Path(__file__).resolve().parent / "net_agents" / "context"
_AGENT_DOC_MAP = {
    "hermes": "hermes-voice",
    "voice": "hermes-voice",
    "hermes-voice": "hermes-voice",
    "browser": "browser",
    "bookkeeper": "bookkeeper",
    "orchestrator": "orchestrator",
    "planner": "planner",
    "builder": "builder",
    "memory-coach": "memory-coach",
    "coach": "memory-coach",
}


@app.get("/api/agent-doc")
def get_agent_doc(name: str = "") -> dict:
    """Return the markdown doc for an agent node so the frontend can display
    it. Read-only, public (like /api/dashboard-state). Never 500s.

    Security: only files that already exist inside the exact context dir are
    served. Names containing "/", "\\" or ".." are rejected outright, and the
    resolved target must sit directly in CONTEXT_DIR — so path traversal is
    impossible.
    """
    raw = (name or "").strip().lower()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        return {"name": name, "found": False, "markdown": ""}
    # known aliases first; otherwise fall back to context/<name>.md directly, so
    # builder-generated agents (which write their own context md) are served too.
    stem = _AGENT_DOC_MAP.get(raw) or (raw if re.fullmatch(r"[a-z0-9_-]{1,40}", raw) else None)
    if not stem:
        return {"name": name, "found": False, "markdown": ""}
    try:
        context_root = CONTEXT_DIR.resolve()
        target = (context_root / f"{stem}.md").resolve()
        if target.parent != context_root or not target.is_file():
            return {"name": name, "found": False, "markdown": ""}
        return {"name": name, "found": True, "markdown": target.read_text(encoding="utf-8")}
    except Exception as e:  # never break the frontend over a bad read
        log.warning("agent-doc read failed for %r: %s", name, e)
        return {"name": name, "found": False, "markdown": ""}


@app.get("/api/agent-memory")
def get_agent_memory(name: str = "") -> dict:
    """Read-only view of an agent's live stored memory, for the dashboard
    drawer (so clicking a node can show the bookkeeper's actual items).

    Public + read-only (like /api/dashboard-state). Never 500s: any error
    returns {"found": False}.

    Security: `name` only selects between a couple of *fixed* known state
    files — it is never used to build a path — so path traversal is
    impossible. Only bookkeeper.json / orchestrator_tasks.json are read.
    """
    raw = (name or "").strip().lower()
    net_state_dir = Path(__file__).resolve().parent / "net_agents" / "state"
    try:
        if raw in ("bookkeeper", "memory", "book-keeper"):
            bk_file = net_state_dir / "bookkeeper.json"
            if not bk_file.is_file():
                return {"name": "bookkeeper", "found": False}
            bk_data = json.loads(bk_file.read_text(encoding="utf-8"))
            raw_working = bk_data.get("working") or []
            raw_longterm = bk_data.get("longterm") or []
            working = [
                {
                    "text": i.get("text", ""),
                    "status": i.get("status", "active"),
                    "created": i.get("created", ""),
                }
                for i in raw_working
            ]
            longterm = [
                {
                    "text": i.get("text", ""),
                    "status": i.get("status", "active"),
                    "date": i.get("date") or "",
                }
                for i in raw_longterm
            ]
            today = dt.date.today().strftime("%Y-%m-%d")
            done_today = sum(
                1
                for i in (raw_working + raw_longterm)
                if i.get("status") == "done"
                and str(i.get("created") or "").startswith(today)
            )
            summary = {
                "working_active": sum(1 for i in raw_working if i.get("status") == "active"),
                "working_done": sum(1 for i in raw_working if i.get("status") == "done"),
                "longterm_active": sum(1 for i in raw_longterm if i.get("status") == "active"),
                "done_today": done_today,
            }
            return {
                "name": "bookkeeper",
                "found": True,
                "working": working,
                "longterm": longterm,
                "summary": summary,
            }
        if raw == "orchestrator":
            orch_file = net_state_dir / "orchestrator_tasks.json"
            if not orch_file.is_file():
                return {"name": "orchestrator", "found": False}
            orch = json.loads(orch_file.read_text(encoding="utf-8")) or []
            tasks = [
                {"request": t.get("request", ""), "status": t.get("status", "")}
                for t in orch
            ]
            return {"name": "orchestrator", "found": True, "tasks": tasks}
        return {"name": name, "found": False}
    except Exception as e:  # never break the frontend over a bad read
        log.warning("agent-memory read failed for %r: %s", name, e)
        return {"name": name, "found": False}


@app.get("/api/agents")
def api_agents() -> dict:
    """Live agent roster for the dashboard graph. Static specialists plus any
    builder-generated agents, each with a health probe — so new agents the
    Builder creates automatically appear as nodes the Orchestrator can call."""
    import httpx as _httpx
    static = {
        "bookkeeper": 9102, "browser": 9103, "orchestrator": 9104,
        "builder": 9105, "repair": 9106, "toolsmith": 9107, "router": 9108, "audit": 9109,
    }
    reg = {}
    try:
        reg = json.loads((Path(__file__).resolve().parent / "agents.json").read_text())
    except Exception:
        pass

    def _up(port: int) -> bool:
        try:
            return _httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.5).status_code == 200
        except Exception:
            return False

    agents = []
    for name, port in static.items():
        agents.append({"name": name, "port": port, "generated": False,
                       "state": "ready" if _up(port) else "down",
                       "desc": (reg.get(name) or {}).get("description", "")})
    for name, v in reg.items():
        if isinstance(v, dict) and v.get("generated") and v.get("agent_port"):
            p = v["agent_port"]
            agents.append({"name": name, "port": p, "generated": True,
                           "state": "ready" if _up(p) else "down",
                           "desc": v.get("description", "")})
    return {"agents": agents}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "hub": "hermes"}
