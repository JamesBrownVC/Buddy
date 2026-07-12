"""self_repair — imperative repair actions for the network (pure functions).

Exposed to the Repair Hermes agent as MCP tools (net_mcp/repair_tools.py). The
Hermes agent reads failures and health, then autonomously chooses which of
these to run.
"""
from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATE = ROOT / "state"
VENV_PY = str(ROOT / ".venv" / "bin" / "python")
HERMES = str(Path.home() / ".local" / "bin" / "hermes")

from net_agents.failure_log import recent_failures  # noqa: E402

AGENT_PORTS = {"bookkeeper": 9102, "browser": 9103, "orchestrator": 9104,
               "builder": 9105, "repair": 9106}
BRAIN_PROFILES = ["buddybrain", "browserbrain", "orchbrain"]


def _alive(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200
    except Exception:
        return False


def _browser_ok() -> bool:
    try:
        return httpx.get("http://127.0.0.1:8080/health", timeout=2).text.strip() == "ok"
    except Exception:
        return False


def _proxy_ok() -> bool:
    try:
        return httpx.get("http://127.0.0.1:8650/health", timeout=2).status_code == 200
    except Exception:
        return False


def _agent_port(name: str) -> int | None:
    if name in AGENT_PORTS:
        return AGENT_PORTS[name]
    try:
        return json.loads((ROOT / "agents.json").read_text()).get(name, {}).get("agent_port")
    except Exception:
        return None


def health_report() -> dict:
    h = {n: ("up" if _alive(p) else "DOWN") for n, p in AGENT_PORTS.items()}
    h["stealth_browser"] = "up" if _browser_ok() else "DOWN"
    h["terra_proxy"] = "up" if _proxy_ok() else "DOWN"
    fails = recent_failures(30)
    h["recent_failures"] = len(fails)
    h["failure_kinds"] = dict(Counter(f.get("kind", "") for f in fails).most_common(5))
    return h


def restart_agent(name: str) -> str:
    port = _agent_port(name)
    if not port:
        return f"unknown agent '{name}'"
    subprocess.run(["pkill", "-f", f"net_agents.{name}:app"], capture_output=True)
    subprocess.Popen([VENV_PY, "-m", "uvicorn", f"net_agents.{name}:app",
                      "--port", str(port)],
                     stdout=open(STATE / f"{name}.log", "a"),
                     stderr=subprocess.STDOUT, cwd=str(ROOT))
    return f"restarted {name} on :{port}"


def recreate_browser() -> str:
    subprocess.run(["docker", "rm", "-f", "browser"], capture_output=True)
    r = subprocess.run(["docker", "run", "-d", "--name", "browser",
                        "--restart", "unless-stopped", "-p", "8080:8080",
                        "-p", "5900:5900", "psyb0t/stealthy-auto-browse"],
                       capture_output=True, text=True)
    return "recreated stealth browser container" if r.returncode == 0 \
        else f"docker run failed: {r.stderr[:200]}"


def restart_proxy() -> str:
    if _proxy_ok():
        return "terra proxy already up"
    subprocess.Popen([VENV_PY, "-m", "uvicorn", "terra_proxy:app", "--port", "8650"],
                     stdout=open(STATE / "terra_proxy.log", "a"),
                     stderr=subprocess.STDOUT, cwd=str(ROOT))
    return "restarted terra proxy (:8650)"


def restart_brain(profile: str) -> str:
    subprocess.run(["pkill", "-f", f"{profile} gateway"], capture_output=True)
    subprocess.Popen([HERMES, "-p", profile, "gateway", "run", "--force"],
                     stdout=open(STATE / f"hermes-{profile}.log", "a"),
                     stderr=subprocess.STDOUT, cwd=str(ROOT))
    return f"restarted Hermes brain '{profile}'"


def auto_repair() -> list[str]:
    """Inspect failures + health and apply the smallest set of fixes."""
    done = []
    kinds = Counter(f.get("kind", "") for f in recent_failures(60))
    if not _browser_ok() or any(k in kinds for k in
                                ("container_down", "container_lookup_failed")):
        done.append(recreate_browser())
    if not _proxy_ok():
        done.append(restart_proxy())
    if sum(v for k, v in kinds.items() if "hermes" in k or "unreachable" in k) >= 2:
        for prof in BRAIN_PROFILES:
            done.append(restart_brain(prof))
    for name, port in AGENT_PORTS.items():
        if name != "repair" and not _alive(port):
            done.append(restart_agent(name))
    return done or ["nothing to repair — system looks healthy"]
