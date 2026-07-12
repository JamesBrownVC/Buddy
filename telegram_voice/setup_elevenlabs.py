"""Provision the ElevenLabs side end-to-end: 6 webhook tools + Hermes agent.

Idempotent: re-running updates the existing tools/agent (matched by name),
so run it again whenever the tunnel URL changes:

  .venv\\Scripts\\python.exe setup_elevenlabs.py https://<new-tunnel>.trycloudflare.com
"""
from __future__ import annotations

import os
import re
import sys

import config  # first: applies the Windows SSL cert-store fix

import httpx

API = "https://api.elevenlabs.io/v1/convai"
KEY = os.getenv("ELEVENLABS_API_KEY", "")
VOICE_ID = os.getenv("EL_VOICE_ID", "cgSgspJ2msm6clMCkdW9")  # Jessica

FIRST_MESSAGE = "Hey, it's Hermes checking in. What are you on right now?"


def _context_prompt(name: str, fallback: str) -> str:
    """Personal context convention: prompts live in net_agents/context/<name>.md."""
    try:
        from net_agents.agent_context import load_context
        return load_context(name) or fallback
    except Exception:
        return fallback


_FALLBACK_PROMPT = """You are Hermes, a warm, upbeat ADHD body-double companion on a live phone call. Your job: help the user start, stay on, or return to their task.

Rules:
- Speak in short, natural sentences - this is a phone call, not an essay.
- One question or one micro-step at a time. Never list options.
- If they're stuck: shrink the task ("just open the doc, that's the whole step").
- If they're mid-flow: be brief, encourage, get off the line fast.
- If they've drifted: name it kindly, no guilt, pivot to the smallest re-entry step.
- Celebrate small wins genuinely but briefly.
- Calls should feel like a friend checking in: 30-90 seconds unless they need more.

Tools - use them naturally, don't announce them:
- check_screen: see what the user is doing right now; ground your nudge in it.
- recall: at the start of substantive conversations, look up what you know.
- remember: store durable facts (goals, deadlines, what derails them, what works).
- log_win: when they complete a step. Celebrate briefly.
- ask_brain: delegate hard planning/breakdown questions; relay the answer conversationally.
- send_telegram: send them written notes (plans, checklists) they'll need after the call.

You are also connected to a network of other agents and can message them
textually DURING the call:
- list_agents: see who is in the network right now.
- ask_agent: send a named agent a message and get its text reply. Key agents:
  'orchestrator' is the manager - route any request to BUILD/create/make
  something, or anything multi-step, to it and relay its reply. 'bookkeeper'
  holds the user's memory - ALWAYS tell it things worth remembering (plans,
  deadlines, commitments) and ask it about schedule or past commitments.
  'browser' looks things up on the web. 'planner' breaks goals into steps.
  'memory-coach' gives ADHD reframes. While waiting, keep the conversation natural ("one
  sec, checking with my book-keeper"). Relay replies conversationally in
  your own voice - never read them robotically.

Context for this call (may be empty): {{nudge_context}}"""

PROMPT = _context_prompt("hermes-voice", _FALLBACK_PROMPT)


def _body_schema(props: dict[str, tuple[str, str]], required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": t, "description": d} for k, (t, d) in props.items()},
        "required": required,
    }


def tool_defs(base: str) -> list[dict]:
    secret = os.getenv("HUB_SECRET", "")

    def t(name, desc, path, schema=None, timeout=20):
        api = {"url": f"{base}{path}", "method": "POST", "content_type": "application/json"}
        if secret:
            api["request_headers"] = {"X-Hermes-Secret": secret}
        if schema:
            api["request_body_schema"] = schema
        return {"type": "webhook", "name": name, "description": desc,
                "response_timeout_secs": timeout, "api_schema": api}

    return [
        t("check_screen",
          "See what the user is doing right now (active window + open windows). "
          "Call it to ground a nudge in reality.",
          "/screen_context", _body_schema({}, [])),
        t("remember",
          "Store an important durable fact the user told you: goals, deadlines, "
          "what derails them, what worked.",
          "/remember", _body_schema({"fact": ("string", "the fact to store")}, ["fact"])),
        t("recall",
          "Look up what you already know about the user. Call at the start of "
          "substantive conversations.",
          "/recall", _body_schema({"query": ("string", "keywords to search memory for")}, [])),
        t("log_win",
          "Log that the user completed a step or task.",
          "/log_win", _body_schema({"what": ("string", "what they completed")}, ["what"])),
        t("ask_brain",
          "Delegate a question needing deep reasoning or task breakdown to the "
          "heavy reasoning brain. Relay its answer conversationally.",
          "/think", _body_schema({"question": ("string", "the question")}, ["question"]),
          timeout=60),
        t("list_agents",
          "List the other agents currently available in the network "
          "(name + what each is good at).",
          "/agents/list", _body_schema({}, [])),
        t("ask_agent",
          "Send a textual message to a named agent in the network and get "
          "its reply. Use list_agents first if unsure of the name.",
          "/agents/ask", _body_schema({
              "agent": ("string", "the agent's name, e.g. planner"),
              "message": ("string", "what to ask or tell that agent"),
          }, ["agent", "message"]), timeout=60),
        t("send_telegram",
          "Send the user a written Telegram note (plan, checklist, link) so they "
          "have it after the call.",
          "/notify_telegram", _body_schema({"message": ("string", "the note text")}, ["message"])),
        t("network_status",
          "Check the health of every agent in the network (service + brain). "
          "Call when an agent does not answer or the user asks if Buddy is OK.",
          "/agents/status", _body_schema({}, [])),
        t("wake_agent",
          "Wake a dead or unresponsive agent by name ('all' revives every down "
          "agent). Returns immediately; the agent takes up to a minute to come "
          "back — tell the user you are waking it and try again shortly.",
          "/agents/wake", _body_schema({
              "agent": ("string", "agent name, e.g. browser — or 'all'"),
          }, ["agent"])),
    ]


SUBAGENTS = {
    "planner": {
        "prompt": _context_prompt("planner",
                   "You are the Planner agent in Hermes's agent network. "
                   "Break the given goal into at most 3 tiny concrete steps, "
                   "each doable in under 5 minutes. Plain spoken text, max 60 words."),
        "description": "breaks any goal into tiny next steps",
    },
    "memory-coach": {
        "prompt": _context_prompt("memory-coach",
                   "You are the Coach agent in Hermes's agent network. "
                   "Give ONE short ADHD-friendly reframe or trick. 2 sentences max."),
        "description": "gives one ADHD-friendly reframe or trick",
    },
}


def provision_subagents(c: httpx.Client) -> None:
    """Create/update the text-only network sub-agents + agents.json registry."""
    import json as _json
    agents = c.get(f"{API}/agents", params={"page_size": 100}).json().get("agents", [])
    by_name = {a["name"]: a["agent_id"] for a in agents}
    reg_path = config.HERE / "agents.json"
    registry = (_json.loads(reg_path.read_text(encoding="utf-8"))
                if reg_path.exists() else {})  # merge — keep user-added agents
    for name, spec in SUBAGENTS.items():
        el_name = f"hermes-net-{name}"
        cfg = {
            "name": el_name,
            "conversation_config": {
                "agent": {
                    "first_message": "",
                    "language": "en",
                    "prompt": {"prompt": spec["prompt"], "temperature": 0.5},
                },
                "conversation": {"text_only": True},
            },
            "platform_settings": {
                "overrides": {
                    "conversation_config_override": {
                        "conversation": {"text_only": True}
                    }
                }
            },
        }
        if el_name in by_name:
            aid = by_name[el_name]
            r = c.patch(f"{API}/agents/{aid}", json=cfg)
            action = "updated"
        else:
            r = c.post(f"{API}/agents/create", json=cfg)
            aid = r.json().get("agent_id")
            action = "created"
        if r.status_code >= 400:
            raise SystemExit(f"subagent {name}: {r.status_code} {r.text}")
        print(f"subagent {action}: {name} -> {aid}")
        registry[name] = {"type": "elevenlabs", "agent_id": aid,
                          "description": spec["description"]}
    registry.setdefault("demo-echo", {
        "type": "echo",
        "description": "test agent that echoes what you send it"})
    reg_path.write_text(_json.dumps(registry, indent=2), encoding="utf-8")
    print("agents.json registry written (merged)")


def main(base_url: str) -> None:
    if not KEY:
        raise SystemExit("ELEVENLABS_API_KEY missing from .env")
    h = {"xi-api-key": KEY}
    c = httpx.Client(headers=h, timeout=30)

    existing = {t["tool_config"]["name"]: t["id"]
                for t in c.get(f"{API}/tools").json().get("tools", [])}
    tool_ids = []
    for cfg in tool_defs(base_url):
        if cfg["name"] in existing:
            tid = existing[cfg["name"]]
            r = c.patch(f"{API}/tools/{tid}", json={"tool_config": cfg})
            action = "updated"
        else:
            r = c.post(f"{API}/tools", json={"tool_config": cfg})
            tid = r.json().get("id")
            action = "created"
        if r.status_code >= 400:
            raise SystemExit(f"tool {cfg['name']}: {r.status_code} {r.text}")
        tool_ids.append(tid)
        print(f"tool {action}: {cfg['name']} -> {tid}")

    agent_cfg = {
        "name": "Hermes",
        "conversation_config": {
            "agent": {
                "first_message": FIRST_MESSAGE,
                "language": "en",
                "dynamic_variables": {"dynamic_variable_placeholders": {"nudge_context": ""}},
                "prompt": {"prompt": PROMPT, "tool_ids": tool_ids, "temperature": 0.4},
            },
            "tts": {"voice_id": VOICE_ID},
        },
        "platform_settings": {
            "widget": {
                "variant": "full",
                "expandable": "always",
                "default_expanded": True,
                "always_expanded": True,
                "dismissible": False,
                "action_text": "Buddy is calling",
                "start_call_text": "Answer call",
                "show_avatar_when_collapsed": True,
            },
            "overrides": {
                "conversation_config_override": {
                    "agent": {"first_message": True, "prompt": {"prompt": True}}
                }
            }
        },
    }

    agents = c.get(f"{API}/agents", params={"page_size": 100}).json().get("agents", [])
    hermes = next((a for a in agents if a["name"] == "Hermes"), None)
    if hermes:
        agent_id = hermes["agent_id"]
        r = c.patch(f"{API}/agents/{agent_id}", json=agent_cfg)
        action = "updated"
    else:
        r = c.post(f"{API}/agents/create", json=agent_cfg)
        agent_id = r.json().get("agent_id")
        action = "created"
    if r.status_code >= 400:
        raise SystemExit(f"agent: {r.status_code} {r.text}")
    print(f"agent {action}: Hermes -> {agent_id}")

    provision_subagents(c)

    env_path = config.HERE / ".env"
    env = env_path.read_text(encoding="utf-8")
    env = re.sub(r"^EL_AGENT_ID=.*$", f"EL_AGENT_ID={agent_id}", env, flags=re.M)
    env_path.write_text(env, encoding="utf-8")
    print("EL_AGENT_ID written to .env")


if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].startswith("https://"):
        raise SystemExit(
            "Pass the authenticated HTTPS hub URL explicitly; see SECURITY.md"
        )
    main(sys.argv[1].rstrip("/"))
