"""Agent network registry — lets the voice agent textually exchange with
other agents mid-call.

Agents are declared in agents.json; each entry is one adapter:

  "name": {"type": "elevenlabs", "agent_id": "agent_...", "description": "..."}
  "name": {"type": "http",  "url": "http://host:port/ask", "description": "..."}
  "name": {"type": "cmd",   "command": "python my_agent.py {message}", "description": "..."}
  "name": {"type": "brain", "persona": "You are ...", "description": "..."}
  "name": {"type": "echo",  "description": "..."}          (wiring test)

elevenlabs agents are messaged over the convai websocket in TEXT-ONLY mode
(real agent-to-agent textual exchange). http agents receive POST
{"message": "...", "from": "hermes-voice"} and must return JSON with a
"reply" (or "answer"/"response"/"message") field — so any teammate's agent
joins the network with one JSON line.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REGISTRY_FILE = HERE / "agents.json"

DEFAULT_REGISTRY = {
    "planner": {
        "type": "brain",
        "persona": ("You are the Planner agent. Break the given goal into at "
                    "most 3 tiny concrete steps, each doable in under 5 "
                    "minutes. Plain spoken text, no markdown."),
        "description": "breaks any goal into tiny next steps",
    },
    "memory-coach": {
        "type": "brain",
        "persona": ("You are the Coach agent. Given what the user is "
                    "struggling with, give ONE short reframe or trick that "
                    "helps ADHD brains, in 2 sentences."),
        "description": "gives one ADHD-friendly reframe or trick",
    },
    "demo-echo": {
        "type": "echo",
        "description": "test agent that echoes what you send it",
    },
}


def load_registry() -> dict:
    if not REGISTRY_FILE.exists():
        REGISTRY_FILE.write_text(json.dumps(DEFAULT_REGISTRY, indent=2),
                                 encoding="utf-8")
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def list_agents() -> list[dict]:
    return [{"name": k, "description": v.get("description", "")}
            for k, v in load_registry().items()]


async def _ask_elevenlabs_ws(agent_id: str, message: str, timeout: float = 30) -> str:
    """Text-only exchange with another ElevenLabs agent over the convai
    websocket. Returns the agent's first text response."""
    import websockets

    key = os.getenv("ELEVENLABS_API_KEY", "")
    r = httpx.get(
        "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
        params={"agent_id": agent_id}, headers={"xi-api-key": key}, timeout=15,
    )
    r.raise_for_status()
    signed_url = r.json()["signed_url"]

    async with websockets.connect(signed_url, open_timeout=15) as ws:
        await ws.send(json.dumps({
            "type": "conversation_initiation_client_data",
            "conversation_config_override": {"conversation": {"text_only": True}},
        }))
        await ws.send(json.dumps({"type": "user_message", "text": message}))
        deadline = asyncio.get_event_loop().time() + timeout
        parts: list[str] = []
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=deadline - asyncio.get_event_loop().time())
            except asyncio.TimeoutError:
                break
            ev = json.loads(raw)
            et = ev.get("type")
            if et == "ping":
                await ws.send(json.dumps({
                    "type": "pong",
                    "event_id": ev.get("ping_event", {}).get("event_id"),
                }))
            elif et == "agent_response":
                parts.append(ev.get("agent_response_event", {}).get("agent_response", ""))
                break
        return " ".join(p for p in parts if p).strip() or "(no reply)"


def ask_agent(name: str, message: str) -> str:
    reg = load_registry()
    if name not in reg:
        known = ", ".join(reg) or "none"
        return f"No agent named '{name}'. Known agents: {known}."
    spec = reg[name]
    kind = spec.get("type", "echo")
    try:
        if kind == "echo":
            return f"[{name}] received: {message}"
        if kind == "elevenlabs":
            return asyncio.run(_ask_elevenlabs_ws(
                spec["agent_id"], message, spec.get("timeout", 30)))
        if kind == "brain":
            from brain import think

            from net_agents.agent_context import load_context
            persona = load_context(name) or spec.get("persona", "")
            return think(message, persona=persona)
        if kind == "http":
            # default aligned to the forwarder->brain timeout (120s) so the hub
            # doesn't abandon at 45s while the brain is still working
            r = httpx.post(spec["url"],
                           json={"message": message, "from": "hermes-voice"},
                           timeout=spec.get("timeout", 120))
            r.raise_for_status()
            d = r.json()
            for key in ("reply", "answer", "response", "message"):
                if isinstance(d, dict) and d.get(key):
                    return str(d[key])
            return json.dumps(d)[:800]
        if kind == "hermes":
            # Direct-to-brain adapter: call the Hermes gateway's OpenAI-compatible
            # endpoint, skipping the redundant per-agent forwarder process. This
            # is what lets forwarders be folded away (Stage 6) without a hop.
            base = spec.get("brain_url") or f"http://127.0.0.1:{spec['brain_port']}/v1"
            key = spec.get("brain_key", "")
            r = httpx.post(f"{base.rstrip('/')}/chat/completions",
                           headers={"Authorization": f"Bearer {key}"},
                           json={"model": "hermes-agent",
                                 "messages": [{"role": "user", "content": message}]},
                           timeout=spec.get("timeout", 120))
            r.raise_for_status()
            content = (r.json()["choices"][0]["message"].get("content") or "").strip()
            return content or "(no reply)"
        if kind == "cmd":
            configured = spec.get("command", "")
            command = (list(configured) if isinstance(configured, list)
                       else shlex.split(str(configured), posix=os.name != "nt"))
            if any("{message}" in arg for arg in command):
                command = [arg.replace("{message}", message) for arg in command]
            else:
                command.append(message)
            out = subprocess.run(
                command, shell=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=spec.get("timeout", 60),
            )
            return (out.stdout or out.stderr or "").strip()[:800] or "(no output)"
        return f"Agent '{name}' has unknown type '{kind}'."
    except Exception as e:
        return f"Agent '{name}' failed: {e}"
