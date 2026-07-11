"""ORCHESTRATOR agent — the working manager of the Hermes network.

It owns the ORGANIGRAMME (who does what, who reports to whom) and drives
every multi-agent job end-to-end. Anything an agent or the user asks lands
on POST /ask; the orchestrator routes it with an LLM tool-loop that can
message every agent in the network through the hub.

The flagship flow — a BUILD TASK ("make me a module for learning
Chinese"), from any agent, runs this pipeline in the background:

  1. CONTEXT   ask the book-keeper what it knows about the user that is
               relevant; optionally send ONE web question to the browser.
  2. USER      if something essential is genuinely unknown, ask the user
               on Telegram (task parks as waiting_user; auto-resumes with
               stated assumptions after ORCH_USER_WAIT seconds, or the
               moment an answer arrives via /user_reply or a call summary).
  3. PRD       write a product-requirements doc -> state/prds/<id>.md
  4. DISPATCH  hand the PRD to the builder agent via the hub (logged on
               the shared event stream like every exchange).
  5. MEMORY    make sure the book-keeper remembers the task + outcome,
               then drop the user a Telegram update.

Everything the orchestrator does goes THROUGH the hub (/agents/ask), so
each hop shows up in state/agent_exchanges.log and on the event stream.

Run:  .venv\\Scripts\\python.exe -m uvicorn net_agents.orchestrator:app --port 9104
Env:  HERMES_HUB, HERMES_SECRET, OPENAI_API_KEY,
      ORCH_MODEL (default gpt-4o), ORCH_USER_WAIT (default 240 s)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

# ── env / paths (self-contained: reads ../.env directly) ──────────────
HERE = Path(__file__).resolve().parent
for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

HUB = os.getenv("HERMES_HUB", "http://localhost:8484").rstrip("/")
SECRET = os.getenv("HERMES_SECRET", os.getenv("HUB_SECRET", ""))
HEADERS = {"X-Hermes-Secret": SECRET}
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("ORCH_MODEL", "gpt-4o")
USER_WAIT_S = int(os.getenv("ORCH_USER_WAIT", "240"))

STATE = HERE / "state"
STATE.mkdir(exist_ok=True)
PRDS = STATE / "prds"
PRDS.mkdir(exist_ok=True)
LEDGER = STATE / "orchestrator_tasks.json"
ORGCHART = STATE / "orgchart.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("orchestrator")

from net_agents.agent_context import load_context  # noqa: E402
PERSONAL_CONTEXT = load_context("orchestrator")

app = FastAPI(title="orchestrator agent")
_lock = threading.Lock()


# ── organigramme ───────────────────────────────────────────────────────
DEFAULT_ORG = {
    "user": {"role": "the human — final authority; reached via Telegram or a Hermes voice call",
             "reports_to": None},
    "orchestrator": {"role": "manager — owns tasks end-to-end, routes work, keeps memory fed",
                     "reports_to": "user"},
    "hermes-voice": {"role": "voice interface — talks to the user live (ElevenLabs)",
                     "reports_to": "orchestrator"},
    "bookkeeper": {"role": "memory — working+long-term memory, nightly dreams; ALL durable facts go here",
                   "reports_to": "orchestrator"},
    "browser": {"role": "research — web lookups, reports condensed answers with sources",
                "reports_to": "orchestrator"},
    "builder": {"role": "execution — receives a PRD and builds/plans the deliverable",
                "reports_to": "orchestrator"},
    "planner": {"role": "voice sub-agent — breaks goals into tiny steps",
                "reports_to": "hermes-voice"},
    "memory-coach": {"role": "voice sub-agent — ADHD reframes",
                     "reports_to": "hermes-voice"},
}


def org_chart() -> dict:
    if not ORGCHART.exists():
        ORGCHART.write_text(json.dumps(DEFAULT_ORG, indent=2), encoding="utf-8")
    org = json.loads(ORGCHART.read_text(encoding="utf-8"))
    # merge in whatever is live on the hub right now
    try:
        r = httpx.post(f"{HUB}/agents/list", headers=HEADERS, timeout=10)
        for a in r.json().get("agents", []):
            org.setdefault(a["name"], {"role": a.get("description", ""),
                                       "reports_to": "orchestrator"})
    except Exception as e:
        log.warning("agents/list failed: %s", e)
    return org


def org_digest() -> str:
    return "\n".join(f"- {name}: {v.get('role','')} (reports to {v.get('reports_to') or '—'})"
                     for name, v in org_chart().items())


# ── network plumbing (everything goes through the hub) ─────────────────
def ask_agent(agent: str, message: str) -> str:
    try:
        r = httpx.post(f"{HUB}/agents/ask", headers=HEADERS,
                       json={"agent": agent, "message": message}, timeout=120)
        return r.json().get("reply", "")
    except Exception as e:
        return f"({agent} unreachable: {e})"


def message_user(text: str) -> bool:
    try:
        r = httpx.post(f"{HUB}/notify_telegram", headers=HEADERS,
                       json={"message": text}, timeout=15)
        return bool(r.json().get("ok"))
    except Exception as e:
        log.warning("notify_telegram failed: %s", e)
        return False


def ring_user(nudge: str) -> bool:
    try:
        r = httpx.post(f"{HUB}/webhook/ring", headers=HEADERS,
                       json={"nudge": nudge, "source": "orchestrator"}, timeout=30)
        return bool(r.json().get("ok"))
    except Exception as e:
        log.warning("ring failed: %s", e)
        return False


def publish(event_type: str, data: dict) -> None:
    try:
        httpx.post(f"{HUB}/webhook/event", headers=HEADERS, timeout=10,
                   json={"type": event_type, "data": data, "source": "orchestrator"})
    except Exception:
        pass


# ── LLM ────────────────────────────────────────────────────────────────
def llm(messages: list[dict], tools: list[dict] | None = None,
        force_json: bool = False) -> dict | None:
    if not OPENAI_KEY:
        return None
    if PERSONAL_CONTEXT and messages and messages[0].get("role") == "system":
        messages = [{"role": "system",
                     "content": PERSONAL_CONTEXT + "\n\n" + messages[0]["content"]},
                    *messages[1:]]
    body: dict = {"model": MODEL, "temperature": 0.3, "messages": messages}
    if tools:
        body["tools"] = tools
    if force_json:
        body["response_format"] = {"type": "json_object"}
    try:
        r = httpx.post("https://api.openai.com/v1/chat/completions",
                       headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                       json=body, timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]
    except Exception as e:
        log.warning("llm failed: %s", e)
        return None


def llm_json(system: str, user: str) -> dict:
    m = llm([{"role": "system", "content": system},
             {"role": "user", "content": user}], force_json=True)
    if m:
        try:
            return json.loads(m["content"])
        except Exception:
            pass
    return {}


# ── task ledger ────────────────────────────────────────────────────────
def _load() -> list[dict]:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return []


def _save(tasks: list[dict]) -> None:
    LEDGER.write_text(json.dumps(tasks, indent=2, ensure_ascii=False),
                      encoding="utf-8")


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def task_log(task_id: str, msg: str, status: str | None = None,
             **fields) -> dict | None:
    """Append to a task's log (and optionally set status/fields), atomically."""
    with _lock:
        tasks = _load()
        t = next((t for t in tasks if t["id"] == task_id), None)
        if not t:
            return None
        t["log"].append(f"[{_now()}] {msg}")
        if status:
            t["status"] = status
        t.update(fields)
        _save(tasks)
        return dict(t)


def get_task(task_id: str) -> dict | None:
    return next((t for t in _load() if t["id"] == task_id), None)


def ledger_digest() -> str:
    tasks = _load()
    if not tasks:
        return "No tasks yet."
    lines = []
    for t in tasks[-12:]:
        lines.append(f"[{t['id']}] {t['status']:>12} :: {t['request'][:80]} "
                     f"(from {t['from']})")
        if t["status"] == "waiting_user" and t.get("question"):
            lines.append(f"          waiting on user: {t['question']}")
    return "\n".join(lines)


# ── the build-task pipeline ────────────────────────────────────────────
CONTEXT_SYSTEM = """You are the Orchestrator agent gathering context before
writing a PRD. You get the task request, the requester, and what the
book-keeper (memory agent) knows. Respond ONLY with JSON:
{
 "research": "ONE web-search question that would materially improve the PRD, or null",
 "ask_user": "ONE short question for the user IF something essential is genuinely unknown and memory doesn't answer it, else null",
 "known": "2-4 sentence summary of the relevant context you already have"
}
Only ask the user when the answer would change the PRD (e.g. skill level,
platform, deadline). Never ask about things memory already answers."""

PRD_SYSTEM = """You are the Orchestrator agent writing a PRD for the builder
agent. Using the request and all gathered context, write a crisp markdown
PRD with exactly these sections:
# <title>
## Goal (1-2 sentences, tied to what we know about THIS user)
## Context (user history / preferences / research that shaped this)
## Requirements (numbered, testable, max 7)
## Non-goals (what NOT to build)
## Success criteria (how the user will know it works)
Keep it under 450 words. No preamble outside the document."""


def run_pipeline(task_id: str) -> None:
    """Stages 1-2 of a build task; parks at waiting_user or falls through
    to finish_pipeline. Runs on a background thread."""
    t = get_task(task_id)
    if not t:
        return
    try:
        # 1. CONTEXT — memory first
        task_log(task_id, "asking book-keeper for relevant context", "gathering_context")
        memory = ask_agent("bookkeeper",
                           f"A task came in: \"{t['request']}\" (from {t['from']}). "
                           "What do you know about the user that is relevant — "
                           "history, preferences, schedule, related past tasks?")
        task_log(task_id, f"book-keeper: {memory[:200]}", memory_context=memory)

        plan = llm_json(CONTEXT_SYSTEM,
                        f"TASK: {t['request']}\nREQUESTER: {t['from']}\n"
                        f"BOOK-KEEPER SAYS: {memory}")
        research_q = plan.get("research")
        if research_q:
            task_log(task_id, f"researching: {research_q}")
            answer = ask_agent("browser", research_q)
            task_log(task_id, f"browser: {answer[:200]}", research=answer)
            # research results are memory too — let the book-keeper cook
            ask_agent("bookkeeper", f"Remember this research finding: "
                                    f"{research_q} -> {answer[:300]}")

        # 2. USER — only if essential info is missing
        question = plan.get("ask_user")
        if question:
            task_log(task_id, f"asking user: {question}", "waiting_user",
                     question=question, known=plan.get("known", ""))
            message_user(f"🧭 Orchestrator — quick question so I can spec "
                         f"\"{t['request'][:60]}\":\n{question}\n"
                         f"(reply here or I'll proceed with sensible "
                         f"assumptions in {USER_WAIT_S // 60} min)")
            publish("task_waiting_user", {"task_id": task_id, "question": question})

            def timeout_resume() -> None:
                cur = get_task(task_id)
                if cur and cur["status"] == "waiting_user":
                    resume_task(task_id, "(no reply — proceed with sensible "
                                         "assumptions and state them in the PRD)")
            threading.Timer(USER_WAIT_S, timeout_resume).start()
            return  # parked; resume_task() finishes the job

        finish_pipeline(task_id, user_answer=None,
                        known=plan.get("known", memory))
    except Exception as e:
        log.exception("pipeline failed")
        task_log(task_id, f"pipeline error: {e}", "failed")


def resume_task(task_id: str, user_answer: str) -> None:
    t = task_log(task_id, f"user answered: {user_answer[:200]}",
                 "building_prd", user_answer=user_answer)
    if t:
        threading.Thread(target=finish_pipeline,
                         args=(task_id,), kwargs={"user_answer": user_answer,
                                                  "known": t.get("known", "")},
                         daemon=True).start()


def finish_pipeline(task_id: str, user_answer: str | None, known: str) -> None:
    t = get_task(task_id)
    if not t:
        return
    try:
        # 3. PRD
        task_log(task_id, "writing PRD", "building_prd")
        parts = [f"REQUEST: {t['request']} (from {t['from']})",
                 f"CONTEXT SUMMARY: {known}",
                 f"BOOK-KEEPER CONTEXT: {t.get('memory_context', '')}"]
        if t.get("research"):
            parts.append(f"RESEARCH: {t['research']}")
        if t.get("question"):
            parts.append(f"WE ASKED THE USER: {t['question']}\n"
                         f"USER ANSWER: {user_answer}")
        m = llm([{"role": "system", "content": PRD_SYSTEM},
                 {"role": "user", "content": "\n\n".join(parts)}])
        prd = (m or {}).get("content") or (
            f"# {t['request']}\n## Goal\n{t['request']}\n"
            f"## Context\n{known}\n## Requirements\n1. Deliver: {t['request']}\n"
            "## Non-goals\n—\n## Success criteria\nUser confirms it helps.")
        prd_file = PRDS / f"{task_id}.md"
        prd_file.write_text(prd, encoding="utf-8")
        task_log(task_id, f"PRD written -> {prd_file.name}",
                 prd_file=str(prd_file))

        # 4. DISPATCH to the builder through the hub (logged exchange)
        task_log(task_id, "dispatching PRD to builder", "dispatched")
        builder_reply = ask_agent(
            "builder", f"New PRD from the orchestrator (task {task_id}). "
                       f"Acknowledge and give your build plan.\n\n{prd}")
        task_log(task_id, f"builder: {builder_reply[:250]}",
                 builder_reply=builder_reply)

        # 5. MEMORY + user update — the book-keeper always gets the outcome
        ask_agent("bookkeeper",
                  f"Remember (important): the user requested \"{t['request']}\" "
                  f"(via {t['from']}); a PRD was delivered to the builder on "
                  f"{_now()[:10]}. Builder said: {builder_reply[:200]}")
        task_log(task_id, "outcome stored with book-keeper", "done")
        publish("task_completed", {"task_id": task_id, "request": t["request"],
                                   "prd_file": str(prd_file)})
        message_user(f"✅ Orchestrator — \"{t['request'][:70]}\" is specced and "
                     f"handed to the builder.\nBuilder says: {builder_reply[:300]}")
    except Exception as e:
        log.exception("finish_pipeline failed")
        task_log(task_id, f"pipeline error: {e}", "failed")


def create_task(request: str, from_agent: str) -> str:
    task = {"id": uuid.uuid4().hex[:8], "request": request, "from": from_agent,
            "status": "intake", "created": _now(), "log": [f"[{_now()}] created"]}
    with _lock:
        tasks = _load()
        tasks.append(task)
        _save(tasks)
    threading.Thread(target=run_pipeline, args=(task["id"],), daemon=True).start()
    publish("task_created", {"task_id": task["id"], "request": request,
                             "from": from_agent})
    return task["id"]


# ── /ask — LLM router with tools over the whole network ────────────────
TOOLS = [
    {"type": "function", "function": {
        "name": "create_build_task",
        "description": "Start the full build pipeline (context -> user -> PRD "
                       "-> builder -> memory) for a request to create/build/"
                       "make something for the user.",
        "parameters": {"type": "object", "properties": {
            "request": {"type": "string"}}, "required": ["request"]}}},
    {"type": "function", "function": {
        "name": "ask_agent",
        "description": "Send a text message to a named agent in the network "
                       "and get its reply (use the org chart for names).",
        "parameters": {"type": "object", "properties": {
            "agent": {"type": "string"}, "message": {"type": "string"}},
            "required": ["agent", "message"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "Store a fact/task/preference with the book-keeper "
                       "(the network's memory). Use for ANY durable information.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "task_status",
        "description": "Current task ledger (all orchestrated tasks + states).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "message_user",
        "description": "Send the user a Telegram text message.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "ring_user",
        "description": "Make Hermes CALL the user (live voice) with a context "
                       "nudge. Only for urgent/interactive matters.",
        "parameters": {"type": "object", "properties": {
            "nudge": {"type": "string"}}, "required": ["nudge"]}}},
]


def run_tool(name: str, args: dict, from_agent: str) -> str:
    if name == "create_build_task":
        tid = create_task(args["request"], from_agent)
        return (f"Build task {tid} started: context is being gathered, the "
                "requester will be updated when the PRD reaches the builder.")
    if name == "ask_agent":
        return ask_agent(args["agent"], args["message"])
    if name == "remember":
        return ask_agent("bookkeeper", f"Remember: {args['text']}")
    if name == "task_status":
        return ledger_digest()
    if name == "message_user":
        return "sent" if message_user(args["text"]) else "failed to send"
    if name == "ring_user":
        return "ringing" if ring_user(args["nudge"]) else "ring failed"
    return f"unknown tool {name}"


ASK_SYSTEM = """You are the ORCHESTRATOR of the user's personal agent
network — the manager who knows everyone and routes all work.

ORGANIGRAMME (live):
{org}

CURRENT TASK LEDGER:
{ledger}

Rules:
- A request to create/build/make something for the user -> create_build_task
  (do NOT try to spec it yourself here; the pipeline handles context, the
  user, the PRD and the builder).
- Any durable fact, preference, schedule item or outcome you learn ->
  remember (the book-keeper must never be bypassed).
- Questions about the user's history/schedule -> ask_agent bookkeeper.
- Things to look up on the web -> ask_agent browser.
- Status questions -> task_status.
- You may chain several tools. Finish with a short plain-text reply to the
  asking agent (spoken-friendly, no markdown)."""


class Ask(BaseModel):
    # optional hint from callers about who is asking (hub sends from=hermes-voice)
    model_config = {"populate_by_name": True}
    message: str
    from_: str = Field("", alias="from")


@app.post("/ask")
def ask(a: Ask) -> dict:
    sender = a.from_ or "unknown-agent"
    log.info("ask from %s: %s", sender, a.message[:120])
    messages = [{"role": "system",
                 "content": ASK_SYSTEM.format(org=org_digest(),
                                              ledger=ledger_digest())},
                {"role": "user", "content": f"(from {sender}) {a.message}"}]
    for _ in range(6):
        m = llm(messages, tools=TOOLS)
        if m is None:  # no LLM -> minimal keyword fallback, never dead
            tid = create_task(a.message, sender)
            return {"reply": f"Task {tid} started (LLM offline, direct intake)."}
        messages.append(m)
        calls = m.get("tool_calls") or []
        if not calls:
            return {"reply": (m.get("content") or "done").strip()}
        for c in calls:
            fn = c["function"]["name"]
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
            except Exception:
                args = {}
            result = run_tool(fn, args, sender)
            log.info("tool %s -> %s", fn, str(result)[:120])
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": str(result)[:4000]})
    return {"reply": "I ran several steps; ask me for task status for details."}


# ── user replies + event stream ────────────────────────────────────────
class UserReply(BaseModel):
    text: str
    task_id: str = ""


@app.post("/user_reply")
def user_reply(u: UserReply) -> dict:
    """Route a user answer to the waiting task (explicit id, or the only/
    latest waiting one)."""
    waiting = [t for t in _load() if t["status"] == "waiting_user"]
    if u.task_id:
        waiting = [t for t in waiting if t["id"] == u.task_id]
    if not waiting:
        return {"ok": False, "error": "no task waiting on the user"}
    resume_task(waiting[-1]["id"], u.text)
    return {"ok": True, "task_id": waiting[-1]["id"]}


MATCH_SYSTEM = """A task is parked waiting for the user to answer a question.
You get the question and a summary of a call the user just had. Respond ONLY
with JSON: {"answers": true/false, "extracted": "the user's answer, if any"}.
answers=true ONLY if the summary genuinely contains the answer."""


class Ev(BaseModel):
    type: str
    ts: str = ""
    data: dict = {}


@app.post("/events")
def events(e: Ev) -> dict:
    """Event-stream inbox: call summaries can answer parked questions."""
    if e.type == "call_ended" and e.data.get("summary"):
        for t in _load():
            if t["status"] == "waiting_user" and t.get("question"):
                v = llm_json(MATCH_SYSTEM,
                             f"QUESTION: {t['question']}\n"
                             f"CALL SUMMARY: {e.data['summary']}")
                if v.get("answers"):
                    resume_task(t["id"], v.get("extracted", e.data["summary"]))
    return {"ok": True}


# ── inspection endpoints ───────────────────────────────────────────────
@app.get("/tasks")
def tasks() -> dict:
    return {"tasks": _load()}


@app.get("/org")
def org() -> dict:
    return {"org": org_chart()}


@app.get("/health")
def health() -> dict:
    ts = _load()
    return {"ok": True, "agent": "orchestrator",
            "tasks": len(ts),
            "waiting_user": sum(1 for t in ts if t["status"] == "waiting_user"),
            "active": sum(1 for t in ts if t["status"] not in
                          ("done", "failed"))}


@app.on_event("startup")
def startup() -> None:
    try:
        httpx.post(f"{HUB}/webhook/subscribe", headers=HEADERS,
                   json={"url": "http://localhost:9104/events"}, timeout=10)
        log.info("subscribed to hub event stream")
    except Exception as e:
        log.warning("subscribe failed: %s", e)
