"""Create the three core Hermes brain profiles (bookkeeper, browser,
orchestrator) that run gpt-5.6-terra through the terra proxy.

Run once after installing Hermes and setting OPENAI_API_KEY in .env:
    .venv/bin/python setup_hermes_brains.py

Each profile gets its own OpenAI-compatible API server on a fixed port, a
strong API key (Hermes requires >=16 chars), and a config pointing at the
terra proxy (:8650) so the agent-loop's requests are sanitised for
gpt-5.6-terra. The builder creates further profiles the same way on demand.
"""
from __future__ import annotations

import os
import secrets
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
for line in (HERE / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
HERMES = str(Path.home() / ".local" / "bin" / "hermes")
PROFILES = Path.home() / ".hermes" / "profiles"
PROXY = os.getenv("TERRA_PROXY_URL", "http://127.0.0.1:8650/v1")

# profile -> (api port, persona md, fixed API key matching the agent's default;
# None -> generate a strong key and write it to state/<profile>.key)
BRAINS = {
    # profile: (api port, persona/self-name, fixed key or None, extra MCP tools)
    "buddybrain": (8643, "bookkeeper", "buddybrain-local", ["net_mcp.memory_tools"]),
    "browserbrain": (8644, "browser", "browserbrain-local", ["net_mcp.browser_tools"]),
    "orchbrain": (8645, "orchestrator", None, []),
    "builderbrain": (8646, "builder", "builderbrain-local", ["net_mcp.builder_tools"]),
    "repairbrain": (8647, "repair", "repairbrain-local", ["net_mcp.repair_tools"]),
    "toolsmithbrain": (8648, "toolsmith", "toolsmithbrain-local", ["net_mcp.toolsmith_tools"]),
    "auditbrain": (8649, "audit", "auditbrain-local", ["net_mcp.audit_tools"]),
}

HVENV = str(Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python")

CONFIG = """# {p} — Hermes brain (gpt-5.6-terra via terra proxy)
model:
  default: "gpt-5.6-terra"
  provider: "openai-direct"
  context_length: 128000
  max_tokens: 4096
providers:
  openai-direct:
    base_url: "{proxy}"
    key_env: "OPENAI_API_KEY"
    api_mode: "chat_completions"
agent:
  max_turns: 20
platform_toolsets:
  api_server: [todo]
mcp_servers:
{mcp}"""


def _mcp_block(self_name: str, extras: list[str]) -> str:
    servers = [("agent_bridge", "net_mcp.agent_bridge"), ("memory_layer", "net_mcp.memory_layer")] + \
        [(m.split(".")[-1], m) for m in extras]
    out = []
    for sid, mod in servers:
        out += [f"  {sid}:",
                f'    command: "{HVENV}"',
                f'    args: ["-m", "{mod}"]',
                "    env:",
                '      HERMES_HUB: "http://127.0.0.1:8484"',
                f'      SELF_AGENT: "{self_name}"',
                f'      PYTHONPATH: "{HERE}"']
    return "\n".join(out) + "\n"

if not OPENAI_KEY:
    raise SystemExit("Set OPENAI_API_KEY in .env first.")

for profile, (port, persona, fixed_key, extras) in BRAINS.items():
    subprocess.run([HERMES, "profile", "create", profile,
                    "--description", f"Hermes brain ({persona})"],
                   capture_output=True, text=True, timeout=90)
    pdir = PROFILES / profile
    key = fixed_key or f"{profile}-{secrets.token_hex(10)}"
    (pdir / ".env").write_text(
        f"OPENAI_API_KEY={OPENAI_KEY}\nAPI_SERVER_ENABLED=true\n"
        f"API_SERVER_KEY={key}\nAPI_SERVER_PORT={port}\n")
    os.chmod(pdir / ".env", 0o600)
    (pdir / "config.yaml").write_text(CONFIG.format(
        p=profile, proxy=PROXY, mcp=_mcp_block(persona, extras)))
    soul = HERE / "net_agents" / "context" / f"{persona}.md"
    if soul.exists():
        (pdir / "SOUL.md").write_text(soul.read_text())
    # a generated key (orchbrain) is read from a state file by its agent
    if fixed_key is None:
        (HERE / "state").mkdir(exist_ok=True)
        (HERE / "state" / f"{profile}.key").write_text(key)
    print(f"created {profile}: api :{port}, SOUL={persona}.md")

print("\nDone. Start everything with:  .venv/bin/python start_all_mac.py")
