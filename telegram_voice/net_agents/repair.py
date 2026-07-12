"""REPAIR agent — keeps the Hermes network healthy and self-healing.

It knows, in detail, what this system is *meant* to be (see SYSTEM_INTENT), it
reads the structured failure log every agent writes to, retrieves the most
relevant recent failures with a tiny local RAG, diagnoses with its own Hermes
brain (gpt-5.6-terra), and executes concrete repair actions — restart a dead
agent, recreate the stealth-browser container, restart a Hermes brain.

Contract: POST /ask {"message": ...} -> {"reply": ...}
  - "scan" / "status"  -> summarise recent failures + system health
  - "repair" / "fix"   -> attempt fixes for the current failures
  - anything else      -> diagnose that specific problem
Run:  .venv/bin/python -m uvicorn net_agents.repair:app --port 9106
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
STATE = ROOT / "state"
VENV_PY = str(ROOT / ".venv" / "bin" / "python")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("repair")

from net_agents.failure_log import recent_failures, log_failure  # noqa: E402

app = FastAPI(title="repair agent")

# ── the detailed statement of user intent this agent defends ──────────────
SYSTEM_INTENT = """You are the REPAIR agent of "Buddy", a modular, auto-expandable
Hermes agent network built to be an external executive function for a user with
ADHD. Understand the intended architecture precisely — your job is to keep
reality matching it:

- Every specialist agent is an independent FastAPI service exposing exactly
  POST /ask {message} -> {reply}. Agents call each other through the hub
  (:8484, /agents/ask). Current agents: bookkeeper (:9102, memory),
  browser (:9103, REAL stealth web browser), orchestrator (:9104, manager),
  builder (:9105, builds NEW agents), and any agent the builder has generated.
- Each agent's PRIMARY brain is its own local Hermes instance running
  gpt-5.6-terra THROUGH the terra proxy (:8650), with a direct gpt-5.6-terra
  fallback. Hermes brains: buddybrain :8643, browserbrain :8644, orchbrain
  :8645, plus one per generated agent. The terra proxy MUST be up for the
  Hermes brains to answer — if many agents fail their 'hermes' backend at once,
  suspect the proxy (:8650) or a dead brain gateway.
- The BROWSER agent must use the VISIBLE stealth browser (Docker container
  'browser', API :8080, live noVNC :5900). It must NOT silently fall back to
  invisible DuckDuckGo text search. A 'container_down' or 'container_lookup_failed'
  failure means the stealth browser is broken and YOU should fix it (recreate
  the Docker container), not accept the degraded mode.
- The network is auto-expandable: the builder creates new agents on demand and
  they must become instantly callable by the others.

Your prime directive: detect what has drifted from this intent and restore it,
preferring the smallest safe action. Always explain what you did in plain text."""

# ── tiny local RAG over the failure log ───────────────────────────────────
def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", str(s).lower()))


def retrieve(query: str, k: int = 8) -> list[dict]:
    """Rank recent failures by keyword overlap + recency (a small, dependency-
    free local RAG). Returns the top-k most relevant records."""
    fails = recent_failures(200)
    if not fails:
        return []
    q = _tokens(query) or {"repair", "fix", "fail"}
    n = len(fails)
    scored = []
    for i, f in enumerate(fails):  # fails is newest-first
        blob = _tokens(f.get("agent", "")) | _tokens(f.get("kind", "")) | \
            _tokens(f.get("detail", "")) | _tokens(json.dumps(f.get("context", {})))
        overlap = len(q & blob)
        recency = (n - i) / n          # 1.0 newest -> ~0 oldest
        scored.append((overlap + 0.5 * recency, f))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in scored[:k]]


# ── concrete repair actions ───────────────────────────────────────────────
AGENT_PORTS = {"bookkeeper": 9102, "browser": 9103, "orchestrator": 9104,
               "builder": 9105, "repair": 9106}
BRAIN_PROFILES = {"buddybrain": 8643, "browserbrain": 8644, "orchbrain": 8645}
HERMES = str(Path.home() / ".local" / "bin" / "hermes")


def _alive(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200
    except Exception:
        return False


def restart_agent(name: str) -> str:
    port = AGENT_PORTS.get(name)
    if not port:
        # maybe a generated agent — look it up in the registry
        try:
            reg = json.loads((ROOT / "agents.json").read_text())
            port = reg.get(name, {}).get("agent_port")
        except Exception:
            port = None
    if not port:
        return f"unknown agent '{name}'"
    subprocess.run(["pkill", "-f", f"net_agents.{name}:app"], capture_output=True)
    subprocess.Popen([VENV_PY, "-m", "uvicorn", f"net_agents.{name}:app",
                      "--port", str(port)],
                     stdout=open(STATE / f"{name}.log", "a"),
                     stderr=subprocess.STDOUT, cwd=str(ROOT))
    return f"restarted {name} on :{port}"


def recreate_browser_container() -> str:
    subprocess.run(["docker", "rm", "-f", "browser"], capture_output=True)
    r = subprocess.run(["docker", "run", "-d", "--name", "browser",
                        "--restart", "unless-stopped", "-p", "8080:8080",
                        "-p", "5900:5900", "psyb0t/stealthy-auto-browse"],
                       capture_output=True, text=True)
    return "recreated stealth browser container" if r.returncode == 0 \
        else f"docker run failed: {r.stderr[:200]}"


def restart_brain(profile: str) -> str:
    subprocess.run(["pkill", "-f", f"{profile} gateway"], capture_output=True)
    subprocess.Popen([HERMES, "-p", profile, "gateway", "run", "--force"],
                     stdout=open(STATE / f"hermes-{profile}.log", "a"),
                     stderr=subprocess.STDOUT, cwd=str(ROOT))
    return f"restarted Hermes brain '{profile}'"


def auto_repair() -> list[str]:
    """Decide + apply fixes from current failures and health. Returns a log."""
    done = []
    fails = recent_failures(60)
    kinds = Counter(f.get("kind", "") for f in fails)

    # 1) stealth browser broken -> recreate the container
    if any(k in kinds for k in ("container_down", "container_lookup_failed")) \
            or not _browser_ok():
        done.append(recreate_browser_container())

    # 2) many hermes-backend failures -> proxy or brains down
    if sum(v for k, v in kinds.items() if "hermes" in k) >= 2 or not _alive_proxy():
        if not _alive_proxy():
            subprocess.Popen([VENV_PY, "-m", "uvicorn", "terra_proxy:app",
                              "--port", "8650"],
                             stdout=open(STATE / "terra_proxy.log", "a"),
                             stderr=subprocess.STDOUT, cwd=str(ROOT))
            done.append("restarted terra proxy (:8650)")
        for prof in BRAIN_PROFILES:
            done.append(restart_brain(prof))

    # 3) any dead agent service -> restart it
    for name, port in AGENT_PORTS.items():
        if name != "repair" and not _alive(port):
            done.append(restart_agent(name))

    return done or ["nothing to repair — system looks healthy"]


def _browser_ok() -> bool:
    try:
        return httpx.get("http://127.0.0.1:8080/health", timeout=2).text.strip() == "ok"
    except Exception:
        return False


def _alive_proxy() -> bool:
    try:
        return httpx.get("http://127.0.0.1:8650/health", timeout=2).status_code == 200
    except Exception:
        return False


# ── diagnosis via the repair agent's own Hermes brain ─────────────────────
def diagnose(query: str, evidence: list[dict]) -> str:
    ev = json.dumps(evidence, ensure_ascii=False)[:3000]
    for base, key, model, gpt5 in [
        (os.getenv("REPAIR_BRAIN_URL", "http://127.0.0.1:8650/v1"),
         OPENAI_KEY, "gpt-5.6-terra", True)]:
        body = {"model": model,
                "messages": [{"role": "system", "content": SYSTEM_INTENT},
                             {"role": "user", "content":
                              f"Problem: {query}\n\nRelevant recent failures "
                              f"(local RAG):\n{ev}\n\nDiagnose the likely root "
                              "cause and name the smallest fix, in 2-4 sentences."}]}
        if gpt5:
            body["reasoning_effort"] = "none"; body["max_completion_tokens"] = 400
        try:
            r = httpx.post(f"{base}/chat/completions",
                           headers={"Authorization": f"Bearer {key}"},
                           json=body, timeout=30)
            r.raise_for_status()
            return (r.json()["choices"][0]["message"].get("content") or "").strip()
        except Exception as e:
            log.warning("diagnose failed: %s", e)
    return "Could not reach my brain to diagnose."


class Ask(BaseModel):
    message: str
    from_: str | None = None


@app.post("/ask")
def ask(a: Ask) -> dict:
    q = a.message.strip().lower()
    try:
        if any(w in q for w in ("repair", "fix", "heal", "restore")):
            actions = auto_repair()
            return {"reply": "Repairs applied:\n- " + "\n- ".join(actions)}
        if any(w in q for w in ("scan", "status", "health", "what's wrong",
                                "whats wrong")):
            fails = recent_failures(30)
            kinds = Counter(f.get("kind", "") for f in fails)
            health = {n: ("up" if _alive(p) else "DOWN")
                      for n, p in AGENT_PORTS.items()}
            health["stealth_browser"] = "up" if _browser_ok() else "DOWN"
            health["terra_proxy"] = "up" if _alive_proxy() else "DOWN"
            summary = (f"{len(fails)} recent failures. Top kinds: "
                       f"{dict(kinds.most_common(4))}. Health: {health}.")
            return {"reply": summary + ("  Say 'repair' and I'll fix the DOWN "
                                        "items." if "DOWN" in str(health) or fails
                                        else "  Everything looks healthy.")}
        # specific problem -> RAG + diagnose
        evidence = retrieve(a.message)
        return {"reply": diagnose(a.message, evidence)}
    except Exception as e:
        log_failure("repair", "self_error", str(e), {"q": q[:200]})
        return {"reply": f"Repair agent hit an error: {e}"}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "agent": "repair",
            "recent_failures": len(recent_failures(200))}
