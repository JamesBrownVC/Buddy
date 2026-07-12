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
    "buddybrain": (8643, "bookkeeper", "buddybrain-local"),
    "browserbrain": (8644, "browser", "browserbrain-local"),
    "orchbrain": (8645, "orchestrator", None),
}

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
"""

if not OPENAI_KEY:
    raise SystemExit("Set OPENAI_API_KEY in .env first.")

for profile, (port, persona, fixed_key) in BRAINS.items():
    subprocess.run([HERMES, "profile", "create", profile,
                    "--description", f"Hermes brain ({persona})"],
                   capture_output=True, text=True, timeout=90)
    pdir = PROFILES / profile
    key = fixed_key or f"{profile}-{secrets.token_hex(10)}"
    (pdir / ".env").write_text(
        f"OPENAI_API_KEY={OPENAI_KEY}\nAPI_SERVER_ENABLED=true\n"
        f"API_SERVER_KEY={key}\nAPI_SERVER_PORT={port}\n")
    os.chmod(pdir / ".env", 0o600)
    (pdir / "config.yaml").write_text(CONFIG.format(p=profile, proxy=PROXY))
    soul = HERE / "net_agents" / "context" / f"{persona}.md"
    if soul.exists():
        (pdir / "SOUL.md").write_text(soul.read_text())
    # a generated key (orchbrain) is read from a state file by its agent
    if fixed_key is None:
        (HERE / "state").mkdir(exist_ok=True)
        (HERE / "state" / f"{profile}.key").write_text(key)
    print(f"created {profile}: api :{port}, SOUL={persona}.md")

print("\nDone. Start everything with:  .venv/bin/python start_all_mac.py")
