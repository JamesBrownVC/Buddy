"""Router — a LIGHTWEIGHT dispatcher (deliberately NOT a Hermes agent).

Its whole job is trivial and latency-critical: given a request an agent can't
handle (or a "who should do this?"), pick the single best agent and forward.
That's a one-shot classification, so it's one fast model call + one hop — no
Hermes runtime, no MCP, no agent-loop. It still plugs into the network through
the same /ask text contract, so any agent calls it as ask_agent('router', ...).

Agents see it in their roster (list_agents) and lean on it when unsure instead
of each carrying the reasoning to scan the whole (growing) roster themselves.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
for _line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())

try:
    from net_agents.failure_log import log_failure
except Exception:
    def log_failure(*a, **k):
        pass

HUB = os.getenv("HERMES_HUB", "http://127.0.0.1:8484").rstrip("/")
MODEL_URL = os.getenv("TERRA_PROXY_URL", "http://127.0.0.1:8650/v1").rstrip("/")
KEY = os.getenv("OPENAI_API_KEY", "")

app = FastAPI(title="router (lightweight dispatcher)")

_SYS = ("You are a router for an agent network. Choose the ONE agent best "
        "suited to handle the request. Reply with ONLY that agent's name — no "
        "punctuation, no explanation. If none fits, reply exactly: none")


class Ask(BaseModel):
    message: str
    from_: str | None = None   # the asking agent, so we never route back to it


def _roster(exclude: str) -> list[dict]:
    try:
        agents = httpx.get(f"{HUB}/api/agents", timeout=8).json().get("agents", [])
    except Exception:
        return []
    skip = {"router", (exclude or "").strip().lower()}
    return [a for a in agents if a["name"].lower() not in skip
            and a.get("state") != "down"]


def _pick(message: str, agents: list[dict]) -> str:
    lines = "\n".join(f"- {a['name']}: {a.get('desc', '')}" for a in agents)
    try:
        r = httpx.post(
            f"{MODEL_URL}/chat/completions",
            headers={"Authorization": f"Bearer {KEY}"},
            json={"model": "gpt-5.6-terra", "reasoning_effort": "none",
                  "max_completion_tokens": 12,
                  "messages": [{"role": "system", "content": _SYS},
                               {"role": "user", "content":
                                f"Agents:\n{lines}\n\nRequest: {message}"}]},
            timeout=20)
        r.raise_for_status()
        return (r.json()["choices"][0]["message"].get("content") or "").strip().lower().strip(".")
    except Exception as e:
        log_failure("router", "pick_failed", str(e), {"message": message[:150]})
        return ""


@app.post("/ask")
def ask(a: Ask) -> dict:
    agents = _roster(a.from_ or "")
    if not agents:
        return {"reply": "No agents available to route to right now."}
    name = _pick(a.message, agents)
    valid = {x["name"].lower() for x in agents}
    if name not in valid:                       # tolerate fuzzy model output
        name = next((x["name"] for x in agents if x["name"].lower() in name), "")
    if not name or name == "none":
        return {"reply": "No agent in the network is suited to that."}
    try:
        reply = httpx.post(f"{HUB}/agents/ask",
                           json={"agent": name, "message": a.message},
                           timeout=120).json().get("reply", "")
        return {"reply": f"[routed to {name}] {reply}"}
    except Exception as e:
        log_failure("router", "forward_failed", str(e), {"target": name})
        return {"reply": f"Routed to {name} but couldn't reach it: {e}"}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "agent": "router", "runtime": "lightweight"}
