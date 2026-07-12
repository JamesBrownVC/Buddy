"""memory_layer — every Hermes agent's own memory, as MCP tools.

Attached to each agent's profile (namespaced by SELF_AGENT), giving it a private
bell-curve + long-term memory. Agents use it to remember what matters and recall
it when relevant — attention-weighted toward what's recent and important.
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from net_agents import memory_store

SELF = os.getenv("SELF_AGENT", "agent").strip().lower()

mcp = FastMCP("memory_layer")


@mcp.tool()
def remember(text: str, importance: float = 0.5) -> str:
    """Save something to YOUR own memory (a fact, a result, a preference you
    learned). importance is 0-1 — higher means it surfaces more strongly later.
    This memory decays with time unless it's important; use remember_longterm
    for durable facts."""
    memory_store.remember(SELF, text, importance, longterm=False)
    return f"remembered: {text[:80]}"


@mcp.tool()
def remember_longterm(text: str) -> str:
    """Save a durable fact to your LONG-TERM memory — it never decays (stable
    facts about the user, the situation, or how to do your job)."""
    memory_store.remember(SELF, text, 0.9, longterm=True)
    return f"stored long-term: {text[:80]}"


@mcp.tool()
def recall(query: str) -> str:
    """Recall from your own memory. Results are ranked by relevance x recency
    (a bell-curve around now, so recent things get more attention) x importance,
    and always include your long-term facts. Call this before answering when
    prior context might matter."""
    hits = memory_store.recall(SELF, query)
    if not hits:
        return "nothing relevant in your memory"
    return "\n".join(f"- {h['text']}" + (" [long-term]" if h.get("longterm") else "")
                     for h in hits)


if __name__ == "__main__":
    mcp.run()
