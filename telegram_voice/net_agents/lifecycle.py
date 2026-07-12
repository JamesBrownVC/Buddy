"""lifecycle — wake, revive and health-check the agent network from anywhere.

One shared engine, exposed three ways:
  * hub auto-wake: a message to a down agent's mailbox (/agents/ask) revives it
  * MCP lifecycle_tools: the repair and audit agents heal the network themselves
  * ElevenLabs tools: the voice agent can wake agents mid-call

Waking is idempotent and safe: names are validated against the known topology,
and `hermes gateway run --replace` clears stale locks / hijacked instances.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import httpx

TV = Path(__file__).resolve().parent.parent          # telegram_voice/
PY = TV / ".venv" / "bin" / "python"
HERMES = Path.home() / ".local" / "bin" / "hermes"
PROFILES = Path.home() / ".hermes" / "profiles"
LOGS = TV / "state"

# Messaging-platform env vars that must NOT leak into an agent brain's gateway.
# A brain gateway is inference-only (api_server); if it inherits the Telegram bot
# token it tries to connect Telegram and collides with the real bot ("token
# already in use"), which wedges startup and leaves the brain 'down'. Only the
# bot process should own these.
_PLATFORM_ENV = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS",
                 "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN")


def brain_env() -> dict:
    """os.environ minus the messaging-platform tokens — the env a brain gateway
    should be launched with so it runs api_server only, never a chat platform."""
    return {k: v for k, v in os.environ.items() if k not in _PLATFORM_ENV}

FIRST_CLASS = {
    "bookkeeper":   {"port": 9102, "profile": "buddybrain"},
    "browser":      {"port": 9103, "profile": "browserbrain"},
    "orchestrator": {"port": 9104, "profile": "orchbrain"},
    "builder":      {"port": 9105, "profile": "builderbrain"},
    "repair":       {"port": 9106, "profile": "repairbrain"},
    "toolsmith":    {"port": 9107, "profile": "toolsmithbrain"},
    "router":       {"port": 9108, "profile": None},   # lightweight, no brain
    "audit":        {"port": 9109, "profile": "auditbrain"},
    "personal":     {"port": 9112, "profile": "personalbrain"},
}


def topology() -> dict[str, dict]:
    agents = dict(FIRST_CLASS)
    try:
        reg = json.loads((TV / "agents.json").read_text(encoding="utf-8"))
        for name, v in reg.items():
            if not (isinstance(v, dict) and v.get("generated") and v.get("agent_port")):
                continue
            profile = f"{name}brain"
            agents[name] = {"port": v["agent_port"],
                            "profile": profile if (PROFILES / profile).exists() else None}
    except Exception:
        pass
    return agents


def _health(port: int) -> tuple[bool, str]:
    """(service reachable, brain 'up'/'down'/'-')."""
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=3)
        brain = r.json().get("brain", "-") if r.headers.get(
            "content-type", "").startswith("application/json") else "-"
        return True, brain
    except Exception:
        return False, "-"


def status() -> list[dict]:
    out = []
    for name, spec in topology().items():
        service, brain = _health(spec["port"])
        healthy = service and (brain in ("up", "-") or spec["profile"] is None)
        out.append({"agent": name, "port": spec["port"], "service": service,
                    "brain": brain, "healthy": healthy})
    return out


def _spawn(args: list[str], logname: str, env: dict | None = None) -> None:
    LOGS.mkdir(exist_ok=True)
    with open(LOGS / logname, "a") as log:
        subprocess.Popen(args, cwd=TV, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True, env=env)


def wake(name: str, wait: float = 90.0) -> dict:
    """Revive one agent: restart its service and/or Hermes brain if down, then
    wait (bounded) until it is healthy. Validated against the topology — the
    only thing this can do is start known agents."""
    name = (name or "").strip().lower()
    spec = topology().get(name)
    if spec is None:
        return {"agent": name, "ok": False,
                "detail": f"unknown agent; known: {', '.join(topology())}"}

    actions = []
    service, brain = _health(spec["port"])
    if not service:
        _spawn([str(PY), "-m", "uvicorn", f"net_agents.{name}:app",
                "--port", str(spec["port"])], f"{name}.log")
        actions.append("started service")
    if spec["profile"] and brain != "up":
        # --replace also clears stale gateway locks and hijacked instances;
        # brain_env() strips the Telegram token so the gateway won't fight the
        # bot for it (the cause of wedged, 'down' brains).
        _spawn([str(HERMES), "-p", spec["profile"], "gateway", "run", "--replace"],
               f"hermes-{spec['profile']}.log", env=brain_env())
        actions.append(f"restarted brain ({spec['profile']})")
    if not actions:
        return {"agent": name, "ok": True, "detail": "already healthy"}

    deadline = time.time() + wait
    while time.time() < deadline:
        service, brain = _health(spec["port"])
        if service and (spec["profile"] is None or brain in ("up", "-")):
            # old-style services report brain "-"; give a fresh brain a moment
            if brain == "up" or spec["profile"] is None:
                return {"agent": name, "ok": True,
                        "detail": "revived: " + ", ".join(actions)}
        time.sleep(3)
    return {"agent": name, "ok": False,
            "detail": f"still not healthy after {int(wait)}s ({', '.join(actions)})"}


def wake_all_down(wait: float = 90.0) -> list[dict]:
    down = [s["agent"] for s in status() if not s["healthy"]]
    return [wake(n, wait) for n in down]


# Agents worth warming the instant a call starts — they take seconds to boot, so
# waking them at call-start means they're ready by the time the user asks.
CORE_AGENTS = ("orchestrator", "browser", "bookkeeper")

import threading as _threading
_warm_lock = _threading.Lock()
_warm_until = 0.0


def warm_core(agents: tuple[str, ...] = CORE_AGENTS, cooldown: float = 30.0) -> None:
    """Fire-and-forget: revive any core agent that isn't already healthy.
    Debounced: several call-start events in one boot window collapse to a SINGLE
    restart attempt, so concurrent prewarms don't fire racing `--replace`s for
    the same brain (which would kill each other). wake() is idempotent."""
    global _warm_until
    now = time.time()
    with _warm_lock:
        if now < _warm_until:
            return                       # already warming in this boot window
        _warm_until = now + cooldown
    healthy = {s["agent"] for s in status() if s["healthy"]}
    for name in agents:
        if name not in healthy:
            try:
                wake(name, wait=0.0)     # kick the restart; don't block the caller
            except Exception:
                pass
