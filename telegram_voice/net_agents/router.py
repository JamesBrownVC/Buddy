"""Router — a LIGHTWEIGHT, POWERLESS injection firewall + dispatcher.

Its whole job is trivial and latency-critical: given a request an agent can't
handle (or a "who should do this?"), pick the single best agent. That's a
one-shot classification — one cheap model call, no Hermes runtime, no agent-loop.

Because it is the low-power FIRST CONTACT for a request, it is also the mesh's
injection firewall. Its single classify call is guarded by honeytoken "tools"
(net_agents.injection_guard): a pure name-picker never calls them, so if injected
text hijacks the model into calling one, that is a high-precision compromise
signal. On such a trip the router QUARANTINES the one request (drops it, zero
blast radius), logs a security event, and lets the lockdown state machine decide
whether repeated trips warrant narrowing high-power routing — it never kills or
restarts anything.

Two contracts:
  POST /ask   -> {"reply": ...}  (back-compat: classify, gate, forward, relay)
  POST /route -> structured Verdict {decision, agent, threat, canary, reply}
                 for the hub-side cutover that will own forwarding.
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
_ENV = HERE.parent / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

from net_agents import injection_guard, lockdown, security_events

try:
    from net_agents.failure_log import log_failure
except Exception:
    def log_failure(*a, **k):
        pass

HUB = os.getenv("HERMES_HUB", "http://127.0.0.1:8484").rstrip("/")
MODEL_URL = os.getenv("TERRA_PROXY_URL", "http://127.0.0.1:8650/v1").rstrip("/")
KEY = os.getenv("OPENAI_API_KEY", "")
HUB_HEADERS = ({"X-Hermes-Secret": os.getenv("HUB_SECRET", "")}
               if os.getenv("HUB_SECRET", "") else {})

app = FastAPI(title="router (powerless injection firewall)")


class Ask(BaseModel):
    message: str
    from_: str | None = None   # the asking agent, so we never route back to it
    hop: int = 0               # delegation depth, threaded through the hub's cap


def _roster(exclude: str) -> list[dict]:
    try:
        agents = httpx.get(f"{HUB}/api/agents", headers=HUB_HEADERS,
                           timeout=8).json().get("agents", [])
    except Exception:
        return []
    skip = {"router", (exclude or "").strip().lower()}
    return [{"name": a["name"], "desc": a.get("desc", "")}
            for a in agents if a["name"].lower() not in skip
            and a.get("state") != "down"]


def _model_call(messages, tools, tool_choice, max_tokens) -> dict:
    """The router's single classify call. gpt-5.6-terra allows tools only with
    reasoning_effort=none (terra_proxy forces this and preserves tools)."""
    r = httpx.post(
        f"{MODEL_URL}/chat/completions",
        headers={"Authorization": f"Bearer {KEY}"},
        json={"model": "gpt-5.6-terra", "reasoning_effort": "none",
              "max_completion_tokens": max_tokens, "messages": messages,
              "tools": tools, "tool_choice": tool_choice},
        timeout=20)
    r.raise_for_status()
    return r.json()


def _on_trip(canary: str, message: str, asker: str) -> None:
    """A honeytoken fired. Record it, update the lockdown counter, and alert the
    user — all rate-limited and non-destructive. Never raises."""
    try:
        security_events.record("honeytoken_trip",
                               {"canary": canary, "from": asker,
                                "message": message[:300]})
        import time as _t
        now = int(_t.time())
        state = lockdown.load()
        state, engaged = lockdown.register_trip(state, now)
        alert = None
        if engaged:
            alert = ("🔒 Buddy security: repeated prompt-injection attempts "
                     "detected — high-power agents (browser, personal) are "
                     "temporarily restricted. Reply /unlock to clear.")
            security_events.record("lockdown_engaged", {"canary": canary})
        elif lockdown.should_alert(state, now):
            alert = (f"⚠️ Buddy security: a request tried to trigger a "
                     f"protected action ({canary}) and was blocked.")
        # The engage transition ALWAYS alerts (bypasses the per-trip cooldown) so
        # a recent low-severity warning can't swallow the lockdown notice.
        if alert and (engaged or lockdown.should_alert(state, now)):
            try:
                httpx.post(f"{HUB}/notify_telegram", headers=HUB_HEADERS,
                           json={"message": alert}, timeout=10)
            except Exception:
                pass
            state = lockdown.mark_alert(state, now)
        lockdown.save(state)
    except Exception as e:
        log_failure("router", "trip_handler_failed", str(e), {})


def _classify(message: str, asker: str) -> tuple[injection_guard.Verdict, list[dict]]:
    roster = _roster(asker)
    if not roster:
        return injection_guard.Verdict("refuse", reply="no agents reachable"), roster
    verdict = injection_guard.classify(message, roster, _model_call)
    if verdict.decision == "quarantine":
        _on_trip(verdict.canary, message, asker)
    elif verdict.threat == "suspicious":
        security_events.record("suspicious",
                               {"from": asker, "hits": verdict.prefilter,
                                "message": message[:300]})
    return verdict, roster


def _escalate(message: str, asker: str, hop: int = 0) -> dict:
    """No single agent fit — escalate to the orchestrator, which force-routes to
    the best fit or decides to build a new agent/tool."""
    if (asker or "").strip().lower() == "orchestrator":
        return {"reply": "No agent in the network is suited to that."}
    # The orchestrator is HIGH_POWER (it can force-route or build). Under a
    # lockdown, escalation must be refused too — otherwise the refuse/failure
    # path becomes a hole straight through the containment to the strongest agent.
    import time as _t
    if lockdown.should_refuse(lockdown.load(), "orchestrator", int(_t.time())):
        return {"reply": "No agent fit and escalation is restricted by a "
                         "security lockdown; try a low-power agent or /unlock."}
    try:
        reply = httpx.post(
            f"{HUB}/agents/ask",
            headers=HUB_HEADERS,
            json={"agent": "orchestrator", "from": "router", "hop": hop + 1,
                  "message": f"[Escalated by the router — no single existing "
                             f"agent could clearly handle this. Force-route it "
                             f"to the best fit, or build a new agent/tool if a "
                             f"genuinely new capability is needed.] {message}"},
            timeout=200).json().get("reply", "")
        return {"reply": f"[escalated to orchestrator] {reply}"}
    except Exception as e:
        log_failure("router", "escalate_failed", str(e), {"message": message[:150]})
        return {"reply": f"No agent fit and the orchestrator was unreachable: {e}"}


@app.post("/route")
def route(a: Ask) -> dict:
    """Structured classification verdict — no forwarding. This is the contract the
    hub will consume when it takes over forwarding (powerless-router cutover)."""
    verdict, _ = _classify(a.message, a.from_ or "")
    import time as _t
    if verdict.decision == "route" and lockdown.should_refuse(
            lockdown.load(), verdict.agent, int(_t.time())):
        return {"decision": "refuse", "agent": verdict.agent, "threat": verdict.threat,
                "reply": f"'{verdict.agent}' is restricted (security lockdown)."}
    return {"decision": verdict.decision, "agent": verdict.agent,
            "threat": verdict.threat, "canary": verdict.canary,
            "reply": verdict.reply}


@app.post("/ask")
def ask(a: Ask) -> dict:
    """Back-compat forwarding path: classify (guarded), enforce the lockdown gate,
    then forward to the chosen agent and relay its reply."""
    verdict, roster = _classify(a.message, a.from_ or "")

    if verdict.decision == "quarantine":
        return {"reply": verdict.reply}
    if verdict.decision == "refuse":
        return _escalate(a.message, a.from_ or "", a.hop)

    import time as _t
    if lockdown.should_refuse(lockdown.load(), verdict.agent, int(_t.time())):
        return {"reply": f"'{verdict.agent}' is temporarily restricted by a "
                         f"security lockdown; try a low-power agent or /unlock."}

    try:
        # carry hop+1 so the hub's hop-depth cap bounds a router->…->router loop
        reply = httpx.post(f"{HUB}/agents/ask",
                           headers=HUB_HEADERS,
                           json={"agent": verdict.agent, "message": a.message,
                                 "from": "router", "hop": a.hop + 1},
                           timeout=120).json().get("reply", "")
        return {"reply": f"[routed to {verdict.agent}] {reply}"}
    except Exception as e:
        log_failure("router", "forward_failed", str(e), {"target": verdict.agent})
        return _escalate(a.message, a.from_ or "", a.hop)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "agent": "router", "runtime": "lightweight"}
