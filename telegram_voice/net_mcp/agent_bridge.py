"""agent_bridge — MCP tools that let a Hermes agent talk to its peers.

Every agent in the network is a Hermes autonomous agent. This stdio MCP server
is attached to each Hermes profile so the agent can, of its own accord, discover
and message the other agents over text — genuine autonomous inter-agent
communication, no orchestration hard-coded in Python.

Tools exposed:
  list_agents()            -> names + one-line role of every reachable agent
  ask_agent(agent, text)   -> send text to another agent, return its reply

Config (per Hermes profile config.yaml):
  mcp_servers:
    agent_bridge:
      command: "<hermes venv python>"
      args: ["-m", "net_mcp.agent_bridge"]
      env: { HERMES_HUB: "http://127.0.0.1:8484", SELF_AGENT: "<name>" }

SELF_AGENT is passed so an agent never calls itself into a loop.
"""
from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

HUB = os.getenv("HERMES_HUB", "http://127.0.0.1:8484").rstrip("/")
SELF = os.getenv("SELF_AGENT", "").strip().lower()

mcp = FastMCP("agent_bridge")


@mcp.tool()
def list_agents() -> str:
    """List the other agents you can message, with a one-line role for each.
    Use this to decide who to delegate a subtask to."""
    try:
        r = httpx.get(f"{HUB}/api/agents", timeout=10)
        rows = []
        for a in r.json().get("agents", []):
            if a["name"].lower() == SELF:
                continue
            desc = (a.get("desc") or "").strip()
            rows.append(f"- {a['name']}: {desc}" if desc else f"- {a['name']}")
        return "\n".join(rows) or "(no other agents reachable right now)"
    except Exception as e:
        return f"could not list agents: {e}"


@mcp.tool()
def ask_agent(agent: str, message: str) -> str:
    """Send a text message to another agent and return its reply. Use this to
    delegate a subtask to the agent best suited for it (e.g. 'browser' for web
    facts, 'bookkeeper' for the user's schedule/memory, 'orchestrator' to run a
    multi-step build). `agent` is the target's name; `message` is plain text."""
    target = (agent or "").strip().lower()
    if not target:
        return "no agent name given"
    if target == SELF:
        return "that's you — answer it yourself instead of delegating"
    try:
        r = httpx.post(f"{HUB}/agents/ask",
                       json={"agent": target, "message": message}, timeout=90)
        return r.json().get("reply", "") or "(empty reply)"
    except Exception as e:
        return f"could not reach {target}: {e}"


if __name__ == "__main__":
    mcp.run()
