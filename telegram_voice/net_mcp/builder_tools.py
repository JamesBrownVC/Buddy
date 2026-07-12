"""builder_tools — the Builder Hermes agent's power, as an MCP tool.

Attached to the builder's Hermes profile so that Hermes agent autonomously
decides to build a new agent (designing its name/purpose/persona itself) and
calls build_agent to bring it to life.
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from net_agents.agent_factory import build_agent as _build

mcp = FastMCP("builder_tools")


@mcp.tool()
def build_agent(name: str, purpose: str, persona: str) -> str:
    """Create and launch a brand-new agent in the network. It becomes a full
    Hermes autonomous agent (its own Hermes brain + peer-messaging) and is
    instantly reachable by every other agent via ask_agent('<name>').

    name    -> short slug for the agent (e.g. 'weather')
    purpose -> one-line description for the registry / graph
    persona -> the new agent's system prompt: its role, how it answers other
               agents in short plain text, and when to delegate.
    """
    res = _build(name, purpose, persona)
    if res.get("ok"):
        return (f"Built agent '{res['name']}' — a Hermes autonomous agent on "
                f"port {res['agent_port']} (brain :{res['brain_port']}). It is "
                f"registered and starting; any agent can now call it as "
                f"ask_agent('{res['name']}').")
    return f"Could not build it: {res.get('error')}"


if __name__ == "__main__":
    mcp.run()
