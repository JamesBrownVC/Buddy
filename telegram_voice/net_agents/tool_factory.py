"""tool_factory — forge DETERMINISTIC MCP tools and wire them into ONE agent.

Pure functions, exposed to the Toolsmith agent via net_mcp/toolsmith_tools.py.
Philosophy: a tool is deterministic (an API call / calculation), not a
reasoning agent. It is attached to a single specialist agent's Hermes runtime —
other agents delegate to that specialist rather than each carrying the tool.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent          # net_agents/
ROOT = HERE.parent                               # telegram_voice/
GEN = ROOT / "net_mcp" / "generated"
HERMES = str(Path.home() / ".local" / "bin" / "hermes")
HVENV = str(Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python")
PROFILES = Path.home() / ".hermes" / "profiles"
STATE = ROOT / "state"

# A generated tool is a tiny deterministic MCP server: one HTTP GET, text out.
TOOL_TEMPLATE = '''"""{name} — deterministic HTTP tool forged by the Toolsmith.
{description}
"""
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("{name}")


@mcp.tool()
def {name}({params_sig}) -> str:
    """{description}"""
    url = f"{url_template}"
    try:
        r = httpx.get(url, timeout=20,
                      headers={{"User-Agent": "buddy-toolsmith/1.0"}})
        r.raise_for_status()
        return r.text[:4000]
    except Exception as e:
        return f"{name} tool error: {{e}}"


if __name__ == "__main__":
    mcp.run()
'''


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_")[:32] or "tool"


def build_http_tool(name: str, description: str, target_agent: str,
                    url_template: str) -> dict:
    """Generate a deterministic HTTP-GET MCP tool and attach it to
    <target_agent>brain's Hermes profile, then restart that brain."""
    slug = _slug(name)
    target = _slug(target_agent)
    desc = description.replace('"""', "'").strip()
    params = re.findall(r"\{(\w+)\}", url_template)
    params_sig = ", ".join(f"{p}: str" for p in params)

    GEN.mkdir(parents=True, exist_ok=True)
    (GEN / "__init__.py").touch()
    (GEN / f"{slug}.py").write_text(TOOL_TEMPLATE.format(
        name=slug, description=desc, params_sig=params_sig,
        url_template=url_template))

    prof = PROFILES / f"{target}brain"
    cfg = prof / "config.yaml"
    if not cfg.exists():
        return {"ok": False, "error": f"no Hermes profile '{target}brain' to attach to"}
    c = cfg.read_text()
    block = (f"  {slug}:\n"
             f'    command: "{HVENV}"\n'
             f'    args: ["-m", "net_mcp.generated.{slug}"]\n'
             f'    env:\n'
             f'      PYTHONPATH: "{ROOT}"\n')
    if f"net_mcp.generated.{slug}" in c:
        pass  # already attached
    elif "mcp_servers:" in c:
        c = c.replace("mcp_servers:\n", "mcp_servers:\n" + block, 1)
    else:
        c = c.rstrip() + "\n\nmcp_servers:\n" + block
    cfg.write_text(c)

    # restart the target agent's Hermes brain so it discovers the new tool
    subprocess.run(["pkill", "-f", f"{target}brain gateway"], capture_output=True)
    subprocess.Popen([HERMES, "-p", f"{target}brain", "gateway", "run", "--force"],
                     stdout=open(STATE / f"hermes-{target}brain.log", "a"),
                     stderr=subprocess.STDOUT, cwd=str(ROOT))
    return {"ok": True, "tool": slug, "target": target, "params": params}
