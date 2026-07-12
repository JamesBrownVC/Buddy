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
import subprocess
import time
from pathlib import Path

import httpx

TV = Path(__file__).resolve().parent.parent          # telegram_voice/
PY = TV / ".venv" / "bin" / "python"
HERMES = Path.home() / ".local" / "bin" / "hermes"
PROFILES = Path.home() / ".hermes" / "profiles"
LOGS = TV / "state"

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


def _spawn(args: list[str], logname: str) -> None:
    LOGS.mkdir(exist_ok=True)
    with open(LOGS / logname, "a") as log:
        subprocess.Popen(args, cwd=TV, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)


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
        # --replace also clears stale gateway locks and hijacked instances
        _spawn([str(HERMES), "-p", spec["profile"], "gateway", "run", "--replace"],
               f"hermes-{spec['profile']}.log")
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
