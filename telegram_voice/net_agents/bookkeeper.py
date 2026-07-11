"""BOOK-KEEPER agent — the memory of the Hermes network.

Self-contained module; talks to the rest of the network ONLY via text
(hub /agents/ask + event stream). Two memory stores:

  WORKING memory — items anchored to dates in a +/-3-week window around
  today, attention-weighted by a bell curve centered on the present
  (sigma 7 days). Curated nightly by DREAMS.

  LONG-TERM memory — important tasks. An item leaves LTM only when it is
  completed, or its date passed without being deferred.

DREAMS — every night (or POST /dream) the book-keeper reviews everything
and decides: KEEP / DROP (done or irrelevant) / PROMOTE (to long-term) /
RESEARCH (asks the browser agent for info it is missing, stores results).
A dream report is posted to the event stream + the user's Telegram.

Inputs: POST /ask {"message": ...} from any agent (remember / recall /
complete / defer / questions), and call_ended events from the hub — every
call summary is scanned for things worth remembering.

Run:  .venv\\Scripts\\python.exe -m uvicorn net_agents.bookkeeper:app --port 9102
Env:  HERMES_HUB, HERMES_SECRET, OPENAI_API_KEY (falls back to rule-based)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

# ── env / paths (self-contained: reads ../.env directly) ──────────────
HERE = Path(__file__).resolve().parent
for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

HUB = os.getenv("HERMES_HUB", "http://localhost:8484").rstrip("/")
SECRET = os.getenv("HERMES_SECRET", os.getenv("HUB_SECRET", ""))
HEADERS = {"X-Hermes-Secret": SECRET}
# The web-browser agent is SOMEONE ELSE'S module: when it lands, point this
# at their endpoint (env BROWSER_URL). Contract: POST {message, from,
# request_id, reply_to} -> either {"reply": ...} synchronously, or POST
# {request_id, answer} to reply_to later.
BROWSER_URL = os.getenv("BROWSER_URL", "http://localhost:9103/ask")
MY_URL = os.getenv("BOOKKEEPER_URL", "http://localhost:9102").rstrip("/")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
# memory curation needs reliable date math + op discipline -> stronger model
MODEL = os.getenv("BOOKKEEPER_MODEL", "gpt-4o")

STATE = HERE / "state"
STATE.mkdir(exist_ok=True)
DB = STATE / "bookkeeper.json"
DREAMS_LOG = STATE / "dreams.log"

SIGMA_DAYS = 7.0
WINDOW_DAYS = 21
DREAM_HOUR = 3.5  # 03:30 local

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bookkeeper")

from net_agents.agent_context import load_context  # noqa: E402
PERSONAL_CONTEXT = load_context("bookkeeper")

app = FastAPI(title="book-keeper agent")


# ── storage ────────────────────────────────────────────────────────────
def load() -> dict:
    db = {"working": [], "longterm": [], "research": []}
    if DB.exists():
        db.update(json.loads(DB.read_text(encoding="utf-8")))
    return db


def save(db: dict) -> None:
    DB.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")


def today() -> dt.date:
    return dt.date.today()


def attention(item: dict) -> float:
    """Bell curve around today; deferred/undated items sit at the center."""
    d = item.get("date")
    if not d:
        return 0.5
    days = (dt.date.fromisoformat(d) - today()).days
    if abs(days) > WINDOW_DAYS:
        return 0.0
    return math.exp(-(days ** 2) / (2 * SIGMA_DAYS ** 2))


def new_item(text: str, date: str | None, longterm: bool) -> dict:
    return {"id": uuid.uuid4().hex[:8], "text": text, "date": date,
            "created": today().isoformat(), "status": "active",
            "deferred": False, "longterm": longterm}


def digest(db: dict) -> str:
    cal = ", ".join(f"{d:%a} {d.isoformat()}"
                    for d in (today() + dt.timedelta(days=i) for i in range(15)))
    lines = [f"TODAY: {today().isoformat()} ({today():%A})",
             f"CALENDAR (next 14 days): {cal}",
             "WORKING MEMORY (attention 0-1):"]
    for it in sorted(db["working"], key=attention, reverse=True):
        if it["status"] == "active":
            lines.append(f"  [{it['id']}] ({attention(it):.2f}) "
                         f"date={it['date'] or '-'} :: {it['text']}")
    lines.append("LONG-TERM MEMORY:")
    for it in db["longterm"]:
        if it["status"] == "active":
            lines.append(f"  [{it['id']}] date={it['date'] or '-'} "
                         f"deferred={it['deferred']} :: {it['text']}")
    return "\n".join(lines)


# ── LLM ────────────────────────────────────────────────────────────────
def llm(system: str, user: str) -> str | None:
    if not OPENAI_KEY:
        return None
    if PERSONAL_CONTEXT:
        system = PERSONAL_CONTEXT + "\n\n" + system
    try:
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model": MODEL, "temperature": 0.2,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning("llm failed: %s", e)
        return None


ASK_SYSTEM = """You are the Book-keeper agent of a personal-assistant agent
network. You manage the user's memory. You receive one text message from
another agent, plus the current memory digest. Respond ONLY with JSON:
{
 "ops": [  // memory mutations implied by the message (may be empty)
   {"op":"remember","text":"...","date":"YYYY-MM-DD or null","longterm":false},
   {"op":"complete","id":"<id from digest>"},
   {"op":"defer","id":"<id>","new_date":"YYYY-MM-DD"},
   {"op":"drop","id":"<id>","reason":"..."},
   {"op":"research","question":"..."}  // info you lack -> delegate to the web-browser agent
 ],
 "reply": "short plain-text answer to send back to the asking agent"
}
Rules:
- Dates: when a weekday or relative day is mentioned, COPY the exact ISO
  date for it from the CALENDAR line. Never compute dates yourself.
- To move/reschedule an existing item: ONE defer op on its id. Never
  complete it, never create a duplicate remember for a reschedule.
- complete is ONLY for things the user actually finished.
- Mark longterm=true only if the message says it is important / long term.
- For questions, answer from the digest (highest-attention first) in "reply".
- Never invent memory ids."""


def apply_ops(db: dict, ops: list[dict]) -> list[str]:
    applied = []
    for o in ops:
        try:
            if o["op"] == "research":
                outcome = post_research(db, o["question"])
                applied.append(f"research: {o['question'][:50]} -> {outcome}")
            elif o["op"] == "remember":
                item = new_item(o["text"], o.get("date"), bool(o.get("longterm")))
                (db["longterm"] if item["longterm"] else db["working"]).append(item)
                applied.append(f"remembered[{item['id']}] {item['text'][:60]}")
            else:
                pool = db["working"] + db["longterm"]
                it = next((i for i in pool if i["id"] == o.get("id")), None)
                if not it:
                    continue
                if o["op"] == "complete":
                    it["status"] = "done"
                    applied.append(f"completed[{it['id']}]")
                elif o["op"] == "defer":
                    it["date"] = o.get("new_date") or it["date"]
                    it["deferred"] = True
                    applied.append(f"deferred[{it['id']}] -> {it['date']}")
                elif o["op"] == "drop":
                    it["status"] = "dropped"
                    applied.append(f"dropped[{it['id']}] ({o.get('reason','')})")
        except Exception as e:
            log.warning("op failed %s: %s", o, e)
    return applied


# ── /ask — the text interface every other agent uses ───────────────────
class Ask(BaseModel):
    message: str


@app.post("/ask")
def ask(a: Ask) -> dict:
    db = load()
    raw = llm(ASK_SYSTEM, f"{digest(db)}\n\nMESSAGE: {a.message}")
    if raw:
        try:
            out = json.loads(raw)
            applied = apply_ops(db, out.get("ops", []))
            save(db)
            reply = out.get("reply", "noted.")
            if applied:
                log.info("ops: %s", "; ".join(applied))
            return {"reply": reply}
        except Exception as e:
            log.warning("bad llm json: %s", e)
    # rule-based fallback: store statements, list memory for questions
    msg = a.message.strip()
    if msg.endswith("?") or msg.lower().startswith(("what", "when", "list", "any")):
        active = [f"- {i['text']} (date {i['date'] or '-'})"
                  for i in sorted(db["working"], key=attention, reverse=True)
                  if i["status"] == "active"][:8]
        lt = [f"- [LT] {i['text']}" for i in db["longterm"] if i["status"] == "active"]
        return {"reply": "Here is what I hold:\n" + "\n".join(active + lt) or "Memory is empty."}
    db["working"].append(new_item(msg, None, False))
    save(db)
    return {"reply": "Stored in working memory."}


# ── dreams ─────────────────────────────────────────────────────────────
DREAM_SYSTEM = """You are the Book-keeper agent performing its nightly DREAM:
curating the user's memory. You get the full memory digest. Decide for
working-memory items: keep, drop (done / no longer relevant / outside the
+/-3-week window), or promote to long-term (genuinely important beyond 3
weeks). Long-term items may ONLY be dropped if completed, or if their date
passed and they were never deferred. If information is missing that a web
search could resolve, add a research question. Respond ONLY with JSON:
{"drop":[{"id":"...","reason":"..."}], "promote":["id"],
 "research":["question", ...], "report":"3-sentence plain-text summary of
 what you kept, dropped, promoted and why"}"""


def ask_network(agent: str, message: str) -> str:
    try:
        r = httpx.post(f"{HUB}/agents/ask", headers=HEADERS,
                       json={"agent": agent, "message": message}, timeout=90)
        return r.json().get("reply", "")
    except Exception as e:
        return f"({agent} unreachable: {e})"


def _store_research_answer(db: dict, req: dict, answer: str) -> None:
    req["status"] = "answered"
    db["working"].append(new_item(
        f"(research) {req['question']} -> {answer[:300]}",
        today().isoformat(), False))


def post_research(db: dict, question: str) -> str:
    """POST a research request to the web-browser agent (someone else's
    module). Sync reply is stored immediately; otherwise it stays pending
    until the browser agent calls back POST /research_result."""
    req = {"id": uuid.uuid4().hex[:8], "question": question,
           "status": "pending", "asked_at": dt.datetime.now().isoformat(timespec="minutes")}
    db["research"].append(req)
    try:
        httpx.post(f"{HUB}/webhook/event", headers=HEADERS, timeout=5,
                   json={"type": "research_requested", "source": "bookkeeper",
                         "data": {"request_id": req["id"], "question": question}})
    except Exception:
        pass
    try:
        r = httpx.post(BROWSER_URL, timeout=90, headers=HEADERS, json={
            "message": question, "from": "bookkeeper",
            "request_id": req["id"],
            "reply_to": f"{MY_URL}/research_result"})
        answer = r.json().get("reply", "") if r.status_code < 400 else ""
        if answer:
            _store_research_answer(db, req, answer)
            return "answered (sync)"
        return "pending (browser will call back)"
    except Exception as e:
        log.warning("browser agent unreachable: %s", e)
        return f"pending (browser unreachable: {e})"


def dream() -> dict:
    db = load()
    decisions = {"drop": [], "promote": [], "research": [], "report": ""}
    raw = llm(DREAM_SYSTEM, digest(db))
    if raw:
        try:
            decisions.update(json.loads(raw))
        except Exception:
            pass

    # LLM decisions, guarded by the hard LTM rule
    for d in decisions["drop"]:
        pool = db["working"] + db["longterm"]
        it = next((i for i in pool if i["id"] == d.get("id")), None)
        if not it:
            continue
        if it["longterm"]:
            date_passed = it["date"] and dt.date.fromisoformat(it["date"]) < today()
            if not (it["status"] == "done" or (date_passed and not it["deferred"])):
                continue  # LTM items are protected
        it["status"] = "dropped"
    for pid in decisions["promote"]:
        it = next((i for i in db["working"] if i["id"] == pid), None)
        if it and it["status"] == "active":
            it["status"] = "dropped"
            db["longterm"].append({**it, "id": uuid.uuid4().hex[:8],
                                   "status": "active", "longterm": True})

    # rule-based safety net: expire working items far outside the window
    for it in db["working"]:
        if (it["status"] == "active" and it["date"]
                and (today() - dt.date.fromisoformat(it["date"])).days > WINDOW_DAYS):
            it["status"] = "dropped"

    # research: post requests to the (external) web-browser agent
    for q in decisions["research"][:3]:
        post_research(db, q)

    save(db)
    report = decisions.get("report") or "Dream complete."
    with open(DREAMS_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M}] {report}\n")
    try:
        httpx.post(f"{HUB}/webhook/event", headers=HEADERS, timeout=10,
                   json={"type": "dream_report", "data": {"report": report},
                         "source": "bookkeeper"})
        httpx.post(f"{HUB}/notify_telegram", headers=HEADERS, timeout=10,
                   json={"message": f"[dream] {report}"})
    except Exception as e:
        log.warning("dream fan-out failed: %s", e)
    log.info("dream: %s", report)
    return {"report": report, "decisions": decisions}


@app.post("/dream")
def dream_endpoint() -> dict:
    return dream()


# ── async research callback (the browser agent "comes back with info") ─
class ResearchResult(BaseModel):
    request_id: str
    answer: str


@app.post("/research_result")
def research_result(res: ResearchResult) -> dict:
    db = load()
    req = next((r for r in db["research"]
                if r["id"] == res.request_id and r["status"] == "pending"), None)
    if not req:
        return {"ok": False, "error": "unknown or already-answered request_id"}
    _store_research_answer(db, req, res.answer)
    save(db)
    log.info("research callback [%s]: %s", res.request_id, res.answer[:100])
    try:
        httpx.post(f"{HUB}/webhook/event", headers=HEADERS, timeout=5,
                   json={"type": "research_answered", "source": "bookkeeper",
                         "data": {"request_id": res.request_id,
                                  "question": req["question"],
                                  "answer": res.answer[:300]}})
    except Exception:
        pass
    return {"ok": True}


# ── event stream: every call summary flows into memory ────────────────
class Ev(BaseModel):
    type: str
    ts: str = ""
    data: dict = {}


@app.post("/events")
def events(e: Ev) -> dict:
    if e.type == "call_ended" and e.data.get("summary"):
        ask(Ask(message=("Extract anything worth remembering from this call "
                         f"summary, else no ops: {e.data['summary']}")))
        log.info("processed call_ended into memory")
    return {"ok": True}


@app.get("/health")
def health() -> dict:
    db = load()
    return {"ok": True, "agent": "bookkeeper",
            "working": sum(1 for i in db["working"] if i["status"] == "active"),
            "longterm": sum(1 for i in db["longterm"] if i["status"] == "active")}


# ── startup: join the stream + nightly dream scheduler ────────────────
@app.on_event("startup")
def startup() -> None:
    try:
        httpx.post(f"{HUB}/webhook/subscribe", headers=HEADERS,
                   json={"url": "http://localhost:9102/events"}, timeout=10)
        log.info("subscribed to hub event stream")
    except Exception as e:
        log.warning("subscribe failed: %s", e)

    def scheduler() -> None:
        while True:
            now = dt.datetime.now()
            target = now.replace(hour=int(DREAM_HOUR),
                                 minute=int(DREAM_HOUR % 1 * 60),
                                 second=0, microsecond=0)
            if target <= now:
                target += dt.timedelta(days=1)
            time.sleep((target - now).total_seconds())
            try:
                dream()
            except Exception as e:
                log.warning("nightly dream failed: %s", e)

    threading.Thread(target=scheduler, daemon=True).start()
