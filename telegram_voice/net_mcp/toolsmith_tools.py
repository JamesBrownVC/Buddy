"""toolsmith_tools — the Toolsmith agent's power, as an MCP tool.

Attached to the toolsmith's Hermes profile so that Hermes agent autonomously
forges a deterministic tool and attaches it to the right specialist agent.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from net_agents.tool_factory import build_http_tool

mcp = FastMCP("toolsmith_tools")


@mcp.tool()
def build_tool(name: str, description: str, target_agent: str,
               url_template: str) -> str:
    """Forge a DETERMINISTIC HTTP tool and attach it to ONE target agent's
    Hermes runtime. Keep each agent's tools minimal — other agents should
    delegate to the specialist that owns the tool rather than duplicating it.

    name          -> short tool name, e.g. 'get_weather'
    description   -> what it does (becomes the tool's doc the agent reads)
    target_agent  -> the single agent that should own this tool, e.g. 'browser'
    url_template  -> an HTTP GET URL whose {param} placeholders become the
                     tool's arguments. Prefer keyless APIs. Examples:
                       weather   -> https://wttr.in/{location}?format=3
                       dictionary-> https://api.dictionaryapi.dev/api/v2/entries/en/{word}
    """
    res = build_http_tool(name, description, target_agent, url_template)
    if res.get("ok"):
        return (f"Forged deterministic tool '{res['tool']}' (params: "
                f"{res['params']}) and attached it to the {res['target']} agent; "
                f"restarted its runtime. Other agents should delegate to "
                f"{res['target']} for this — no need to give them the tool too.")
    return f"Could not build the tool: {res.get('error')}"


if __name__ == "__main__":
    mcp.run()
