"""One command to bring the whole Hermes/Buddy stack up on macOS.

Starts:  agent hub (:8484) + cloudflared tunnel + Telegram bot listener
         + network agents (bookkeeper :9102, browser :9103, orchestrator :9104).
Then:    reads the fresh tunnel URL, writes HUB_PUBLIC_URL to .env, and
         re-points the ElevenLabs tools at it (setup_elevenlabs).

  .venv/bin/python start_all_mac.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

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


def main() -> None:
    print("[1/5] agent hub :8484")
    spawn([str(PY), "-m", "uvicorn", "agent_hub:app", "--port", "8484"], "hub.log")

    print("[2/5] cloudflared tunnel…")
    tun = subprocess.Popen(
        [CLOUDFLARED, "tunnel", "--url", "http://localhost:8484"],
        cwd=HERE, stderr=subprocess.PIPE, text=True, errors="replace",
    )
    procs.append(tun)
    url = ""
    deadline = time.time() + 60
    for line in tun.stderr:
        m = URL_RE.search(line)
        if m:
            url = m.group(0)
            break
        if time.time() > deadline:
            break
    # keep draining stderr in the background so the pipe never fills
    subprocess.Popen(["cat"], stdin=tun.stderr,
                     stdout=open(LOGS / "tunnel.log", "a"))
    if not url:
        raise SystemExit("tunnel URL not found — is cloudflared installed?")
    print(f"      tunnel: {url}")

    env_path = HERE / ".env"
    env = env_path.read_text()
    if "HUB_PUBLIC_URL=" in env:
        env = re.sub(r"^HUB_PUBLIC_URL=.*$", f"HUB_PUBLIC_URL={url}", env, flags=re.M)
    else:
        env += f"\nHUB_PUBLIC_URL={url}\n"
    env_path.write_text(env)

    print("[3/5] re-pointing ElevenLabs tools at the new URL…")
    r = subprocess.run([str(PY), "setup_elevenlabs.py", url], cwd=HERE)
    if r.returncode != 0:
        print("      WARNING: setup_elevenlabs failed — live-call tools may point at the old URL")

    print("[4/5] telegram bot listener")
    spawn([str(PY), "bot.py"], "bot.log")

    print("[5/5] network agents: bookkeeper :9102, browser :9103, orchestrator :9104")
    spawn([str(PY), "-m", "uvicorn", "net_agents.bookkeeper:app", "--port", "9102"], "bookkeeper.log")
    spawn([str(PY), "-m", "uvicorn", "net_agents.browser:app", "--port", "9103"], "browser.log")
    spawn([str(PY), "-m", "uvicorn", "net_agents.orchestrator:app", "--port", "9104"], "orchestrator.log")

    print("\nHermes stack UP (all local on the Mac mini).")
    print(f"Hub public URL: {url}")
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
