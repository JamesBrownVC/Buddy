"""repair_tools — the Repair Hermes agent's powers, as MCP tools.

Attached to the repair profile so that Hermes agent autonomously inspects the
failure log + health and chooses which fix to apply.
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from net_agents import self_repair
from net_agents.failure_log import recent_failures

mcp = FastMCP("repair_tools")


@mcp.tool()
def scan_health() -> str:
    """Report the current health of every agent, the stealth browser, the terra
    proxy, and a summary of recent failures. Use this first to see what's wrong."""
    return json.dumps(self_repair.health_report(), indent=2)


@mcp.tool()
def recent_failures_log(limit: int = 15) -> str:
    """Return the most recent structured failures other agents have logged —
    your evidence for what to fix (agent, kind, detail, context)."""
    fails = recent_failures(limit)
    if not fails:
        return "no recent failures logged"
    return "\n".join(
        f"[{f.get('ts')}] {f.get('agent')} :: {f.get('kind')} :: {f.get('detail')}"
        for f in fails)


@mcp.tool()
def repair_all() -> str:
    """Inspect failures + health and apply the smallest set of fixes (recreate
    the stealth browser if down, restart the proxy/brains if many hermes
    failures, restart any dead agent)."""
    return "Applied:\n- " + "\n- ".join(self_repair.auto_repair())


@mcp.tool()
def restart_agent(name: str) -> str:
    """Restart a single agent service by name (bookkeeper, browser,
    orchestrator, builder, or a generated agent)."""
    return self_repair.restart_agent(name)


@mcp.tool()
def recreate_browser() -> str:
    """Recreate the stealth-browser Docker container (fixes the visible browser
    when it is down or crash-looping)."""
    return self_repair.recreate_browser()


@mcp.tool()
def restart_brain(profile: str) -> str:
    """Restart a Hermes brain gateway by profile name (buddybrain, browserbrain,
    orchbrain, or <name>brain for a generated agent)."""
    return self_repair.restart_brain(profile)


if __name__ == "__main__":
    mcp.run()
