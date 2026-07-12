"""hermes_service — turn a Hermes autonomous agent into a network service.

Every agent in Buddy IS a Hermes autonomous agent: a Hermes instance (profile)
with its own persona, tools, and MCP peer-calling. This module is the thin
protocol adapter that exposes that agent on the network's `/ask` contract — it
does NO reasoning of its own; it hands the text to the Hermes agent and returns
whatever the Hermes agent autonomously decides to reply.

    # net_agents/bookkeeper.py is just:
    from net_agents.hermes_service import make_agent_app
    app = make_agent_app("bookkeeper", brain_port=8643, brain_key="buddybrain-local")

The Hermes agent handles the request with its full toolset (its role tools +
the agent_bridge MCP tools for messaging peers), asynchronously and autonomously.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

# load .env once (shared by every agent module)
_HERE = Path(__file__).resolve().parent
for _line in (_HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())

try:
    from net_agents.failure_log import log_failure
except Exception:  # pragma: no cover
    def log_failure(*a, **k):
        pass


class Ask(BaseModel):
    message: str
    from_: str | None = None


def make_agent_app(name: str, brain_port: int, brain_key: str,
                   timeout: float = 120.0) -> FastAPI:
    """Build the FastAPI app for a Hermes-backed agent. `/ask` forwards the text
    to this agent's Hermes runtime (its OpenAI-compatible API server, model
    'hermes-agent' = a full autonomous agent turn) and returns its reply."""
    base = os.getenv(f"{name.upper()}_BRAIN_URL", f"http://127.0.0.1:{brain_port}/v1")
    key = os.getenv(f"{name.upper()}_BRAIN_KEY", brain_key)
    app = FastAPI(title=f"{name} agent (Hermes)")

    @app.post("/ask")
    def ask(a: Ask) -> dict:
        try:
            r = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "hermes-agent",
                      "messages": [{"role": "user", "content": a.message}]},
                timeout=timeout)
            r.raise_for_status()
            reply = (r.json()["choices"][0]["message"].get("content") or "").strip()
            if reply:
                return {"reply": reply}
            log_failure(name, "empty_hermes_reply", "agent returned no content",
                        {"message": a.message[:200]})
            return {"reply": "(no reply)"}
        except Exception as e:
            log_failure(name, "hermes_unreachable", str(e),
                        {"message": a.message[:200], "brain": base})
            return {"reply": f"My Hermes runtime is unavailable right now ({e})."}

    @app.get("/health")
    def health() -> dict:
        # the service is only healthy if its Hermes brain answers
        brain = False
        try:
            brain = httpx.get(f"{base}/models",
                              headers={"Authorization": f"Bearer {key}"},
                              timeout=2).status_code == 200
        except Exception:
            brain = False
        return {"ok": True, "agent": name, "runtime": "hermes",
                "brain": "up" if brain else "down"}

    return app
