"""lifecycle_tools — MCP tools that let an agent heal the network itself.

Attached to the repair and audit brains so they can revive dead agents from
afar (James texting from his phone is enough — no laptop needed). They talk
to the lifecycle engine directly, so they work even when the hub is down.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from net_agents import lifecycle

mcp = FastMCP("lifecycle_tools")


@mcp.tool()
def network_status() -> str:
    """Health of every agent in the network: is its service reachable and is
    its Hermes brain up? Call this first when anything seems unresponsive."""
    rows = []
    for s in lifecycle.status():
        state = "HEALTHY" if s["healthy"] else "DOWN"
        rows.append(f"- {s['agent']} (:{s['port']}): {state}"
                    f" — service {'up' if s['service'] else 'DOWN'},"
                    f" brain {s['brain']}")
    return "\n".join(rows)


@mcp.tool()
def wake_agent(name: str) -> str:
    """Revive a dead or unresponsive agent: restarts its service and/or its
    Hermes brain (clearing stale locks) and waits until it is healthy again.
    Use after network_status shows an agent DOWN, or when a peer does not
    answer. Takes up to ~90s."""
    r = lifecycle.wake(name)
    return f"{r['agent']}: {'OK' if r['ok'] else 'FAILED'} — {r['detail']}"


@mcp.tool()
def wake_all_down() -> str:
    """Revive every unhealthy agent in one sweep. Use when several agents are
    down (e.g. after a reboot or a botched restart)."""
    results = lifecycle.wake_all_down()
    if not results:
        return "nothing to do — every agent is healthy"
    return "\n".join(f"- {r['agent']}: {'OK' if r['ok'] else 'FAILED'} — {r['detail']}"
                     for r in results)


if __name__ == "__main__":
    mcp.run()
