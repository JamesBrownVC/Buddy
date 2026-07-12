"""One command to bring the whole Hermes stack up — self-healing URLs.

Starts:  agent hub (:8484) + cloudflared tunnel + Telegram bot listener.
Then:    reads the fresh tunnel URL, writes HUB_PUBLIC_URL to .env, and
         re-points all six ElevenLabs tools at it (setup_elevenlabs).

  .venv\\Scripts\\python.exe start_all.py        (or double-click start_all.bat)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import config  # loads the ignored local .env
from security_utils import ensure_env_secret, set_env_value

HERE = Path(__file__).resolve().parent
PY = HERE / ".venv" / "Scripts" / "python.exe"
CLOUDFLARED = r"C:\Program Files (x86)\cloudflared\cloudflared.exe"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

procs: list[subprocess.Popen] = []


def spawn(args: list[str], **kw) -> subprocess.Popen:
    p = subprocess.Popen(args, cwd=HERE, **kw)
    procs.append(p)
    return p


def main() -> None:
    ensure_env_secret()
    public_tunnel = os.getenv("ENABLE_PUBLIC_TUNNEL", "0").lower() in {
        "1", "true", "yes"
    }
    print("[1/4] agent hub :8484")
    spawn([str(PY), "-m", "uvicorn", "agent_hub:app", "--host",
           os.getenv("BUDDY_BIND_HOST", "127.0.0.1"), "--port", "8484"])

    url = ""
    if public_tunnel:
        print("[2/5] cloudflared tunnel (explicitly enabled)…")
        tun = spawn([CLOUDFLARED, "tunnel", "--url", "http://localhost:8484"],
                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        deadline = time.time() + 60
        for line in tun.stderr:
            m = URL_RE.search(line)
            if m:
                url = m.group(0)
                break
            if time.time() > deadline:
                break
        if not url:
            raise SystemExit("tunnel URL not found — disable ENABLE_PUBLIC_TUNNEL or install cloudflared")
        os.environ["HUB_PUBLIC_URL"] = url
        set_env_value("HUB_PUBLIC_URL", url)
        set_env_value("ENABLE_PUBLIC_TUNNEL", "1")
        print(f"      secured application endpoint: {url}")
        print("[3/5] updating authenticated ElevenLabs tools…")
        subprocess.run([str(PY), "setup_elevenlabs.py", url], cwd=HERE, check=True)
    else:
        os.environ["HUB_PUBLIC_URL"] = os.getenv("LOCAL_HUB_URL", "")
        set_env_value("ENABLE_PUBLIC_TUNNEL", "0")
        print("[2/5] public tunnel disabled (local-only mode)")

    print("[4/5] telegram bot listener")
    spawn([str(PY), "bot.py"])

    print("[5/5] network agents: bookkeeper :9102, browser :9103, orchestrator :9104")
    spawn([str(PY), "-m", "uvicorn", "net_agents.bookkeeper:app", "--port", "9102"])
    spawn([str(PY), "-m", "uvicorn", "net_agents.browser:app", "--port", "9103"])
    spawn([str(PY), "-m", "uvicorn", "net_agents.orchestrator:app", "--port", "9104"])

    print("\nHermes stack UP (local-only by default).")
    print("Private dashboard: .venv\\Scripts\\python.exe open_dashboard.py")
    print("Ctrl+C stops everything.")
    try:
        while True:
            time.sleep(5)
            for p in procs:
                if p.poll() is not None:
                    print(f"process {p.args[0]} exited ({p.returncode})")
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    sys.exit(main())
