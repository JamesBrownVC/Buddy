"""One command to bring the whole Hermes/Buddy stack up on macOS.

Starts:  agent hub (:8484) + cloudflared tunnel + Telegram bot listener
         + network agents (bookkeeper :9102, browser :9103, orchestrator :9104).
Then:    reads the fresh tunnel URL, writes HUB_PUBLIC_URL to .env, and
         re-points the ElevenLabs tools at it (setup_elevenlabs).

  .venv/bin/python start_all_mac.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import config  # loads the ignored local .env
from security_utils import ensure_env_secret, set_env_value

HERE = Path(__file__).resolve().parent
PY = HERE / ".venv" / "bin" / "python"
CLOUDFLARED = shutil.which("cloudflared") or "/opt/homebrew/bin/cloudflared"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
LOGS = HERE / "state"
LOGS.mkdir(exist_ok=True)

procs: list[subprocess.Popen] = []


def spawn(args: list[str], logname: str, **kw) -> subprocess.Popen:
    log = open(LOGS / logname, "a")
    p = subprocess.Popen(args, cwd=HERE, stdout=log, stderr=subprocess.STDOUT, **kw)
    procs.append(p)
    return p


HERMES = Path.home() / ".local" / "bin" / "hermes"
HERMES_BRAINS = [  # (profile, api port) — one Hermes instance per agent brain
    ("buddybrain", 8643),     # bookkeeper
    ("browserbrain", 8644),   # browser
    ("orchbrain", 8645),      # orchestrator
    ("builderbrain", 8646),   # builder
    ("repairbrain", 8647),    # repair
    ("toolsmithbrain", 8648), # toolsmith
    ("auditbrain", 8649),     # audit
    ("personalbrain", 8651),  # personal (LOCAL ollama model)
]


def main() -> None:
    ensure_env_secret()
    bind_host = os.getenv("BUDDY_BIND_HOST", "127.0.0.1")
    public_tunnel = os.getenv("ENABLE_PUBLIC_TUNNEL", "0").lower() in {
        "1", "true", "yes"
    }
    print("[0a/6] terra proxy :8650 (gpt-5.6-terra for the Hermes brains)")
    spawn([str(PY), "-m", "uvicorn", "terra_proxy:app", "--port", "8650"],
          "terra_proxy.log")
    time.sleep(2)

    print("[0b/6] hermes agent brains :8643 :8644 :8645 (+ generated)")
    brains = list(HERMES_BRAINS)
    # include a Hermes brain for every builder-generated agent
    try:
        reg = json.loads((HERE / "agents.json").read_text())
        for name, v in reg.items():
            if isinstance(v, dict) and v.get("generated") and v.get("brain_port"):
                bp = Path.home() / ".hermes" / "profiles" / f"{name}brain"
                if bp.exists():
                    brains.append((f"{name}brain", v["brain_port"]))
    except Exception:
        pass
    for profile, port in brains:
        if (Path.home() / ".hermes" / "profiles" / profile).exists():
            spawn([str(HERMES), "-p", profile, "gateway", "run", "--force"],
                  f"hermes-{profile}.log")
        else:
            print(f"      (profile {profile} missing — skipped)")

    print("[1/6] agent hub :8484")
    spawn([str(PY), "-m", "uvicorn", "agent_hub:app", "--host", bind_host,
           "--port", "8484"], "hub.log")

    url = ""
    if public_tunnel:
        print("[2/6] cloudflared tunnel (explicitly enabled)…")
        tun = subprocess.Popen(
            [CLOUDFLARED, "tunnel", "--url", "http://localhost:8484"],
            cwd=HERE, stderr=subprocess.PIPE, text=True, errors="replace",
        )
        procs.append(tun)
        deadline = time.time() + 60
        for line in tun.stderr:
            m = URL_RE.search(line)
            if m:
                url = m.group(0)
                break
            if time.time() > deadline:
                break
        subprocess.Popen(["cat"], stdin=tun.stderr,
                         stdout=open(LOGS / "tunnel.log", "a"))
        if not url:
            raise SystemExit("tunnel URL not found — disable ENABLE_PUBLIC_TUNNEL or install cloudflared")
        os.environ["HUB_PUBLIC_URL"] = url
        set_env_value("HUB_PUBLIC_URL", url)
        set_env_value("ENABLE_PUBLIC_TUNNEL", "1")
        print(f"      secured application endpoint: {url}")
        print("[3/6] updating authenticated ElevenLabs tools…")
        r = subprocess.run([str(PY), "setup_elevenlabs.py", url], cwd=HERE)
        if r.returncode != 0:
            print("      WARNING: setup_elevenlabs failed — live-call tools were not updated")
    else:
        os.environ["HUB_PUBLIC_URL"] = os.getenv("LOCAL_HUB_URL", "")
        set_env_value("ENABLE_PUBLIC_TUNNEL", "0")
        print("[2/6] public tunnel disabled (local-only mode)")

    print("[4/6] telegram bot listener")
    spawn([str(PY), "bot.py"], "bot.log")

    print("[5/6] network agents: bookkeeper :9102 browser :9103 "
          "orchestrator :9104 builder :9105 repair :9106")
    for name, port in [("bookkeeper", 9102), ("browser", 9103),
                       ("orchestrator", 9104), ("builder", 9105),
                       ("repair", 9106), ("toolsmith", 9107), ("router", 9108), ("audit", 9109),
                       ("personal", 9112)]:
        spawn([str(PY), "-m", "uvicorn", f"net_agents.{name}:app",
               "--port", str(port)], f"{name}.log")

    print("[6/6] builder-generated agents")
    try:
        reg = json.loads((HERE / "agents.json").read_text())
        for name, v in reg.items():
            if isinstance(v, dict) and v.get("generated") and v.get("agent_port"):
                if (HERE / "net_agents" / f"{name}.py").exists():
                    spawn([str(PY), "-m", "uvicorn", f"net_agents.{name}:app",
                           "--port", str(v["agent_port"])], f"{name}.log")
                    print(f"      + {name} :{v['agent_port']}")
    except Exception as e:
        print(f"      (no generated agents: {e})")

    print("\nHermes stack UP (local-only by default).")
    if url:
        print(f"Public URL: {url} (signed call links + authenticated tools)")
    print("Private dashboard: .venv/bin/python open_dashboard.py")
    print("Logs: telegram_voice/state/*.log — Ctrl+C stops everything.")
    try:
        while True:
            time.sleep(5)
            for p in procs:
                if p.poll() is not None:
                    print(f"process {p.args} exited ({p.returncode})")
                    procs.remove(p)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
