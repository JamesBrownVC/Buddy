"""audit_tools — the Audit agent's read access to how the network performed.

Attached to the audit agent's Hermes profile. The audit agent uses these to
judge each action against its ask, then makes surgical improvements by asking
the toolsmith (for tools) or the builder (for agents) via its agent_bridge.
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from net_agents.audit_data import performance_summary, read_tasks

mcp = FastMCP("audit_tools")


@mcp.tool()
def recent_tasks(limit: int = 25) -> str:
    """Recent task records (newest first): for each, who asked (from), which
    agent handled it, the ask, the reply, latency (ms) and whether it succeeded.
    Read these to judge whether each action actually satisfied its ask."""
    tasks = read_tasks(limit)
    if not tasks:
        return "no tasks logged yet"
    out = []
    for t in tasks:
        out.append(f"[{t.get('level')}] {t.get('from')} -> {t.get('agent')} "
                   f"({t.get('ms')}ms, ok={t.get('ok')})\n  ask: {t.get('ask','')[:200]}"
                   f"\n  reply: {t.get('reply','')[:240]}")
    return "\n\n".join(out)


@mcp.tool()
def performance() -> str:
    """Per-agent performance summary over the recent window: task volume,
    failure rate, average/max latency, plus the worst tasks (failed, empty, or
    very slow). Use this to spot recurring problems worth fixing."""
    return json.dumps(performance_summary(), indent=2)


if __name__ == "__main__":
    mcp.run()
