"""Drift watcher — the proactive half of Hermes.

Polls the active window; if you sit on a distracting app for DRIFT_MINUTES,
Hermes rings you (Telegram tap-to-answer live call) with the context of
what it saw. Cooldown prevents nagging.

  .venv\\Scripts\\python.exe watcher.py            (defaults: 10 min drift)
  set DRIFT_MINUTES=1 & .venv\\Scripts\\python.exe watcher.py   (demo mode)
"""
from __future__ import annotations

import asyncio
import os
import time

import config  # first: applies the Windows SSL cert-store fix

from call_live import ring

DISTRACT = [w.strip().lower() for w in os.getenv(
    "DISTRACT_KEYWORDS",
    "twitter,x.com,facebook,instagram,tiktok,youtube,reddit,netflix,twitch,9gag",
).split(",")]
DRIFT_MINUTES = float(os.getenv("DRIFT_MINUTES", "10"))
COOLDOWN_MINUTES = float(os.getenv("COOLDOWN_MINUTES", "15"))
POLL_SECS = 15


def active_title() -> str:
    try:
        import pygetwindow as gw
        w = gw.getActiveWindow()
        return (w.title if w else "") or ""
    except Exception:
        return ""


def is_distracting(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in DISTRACT)


def main() -> None:
    print(f"watching… drift threshold {DRIFT_MINUTES} min, "
          f"keywords: {', '.join(DISTRACT)}")
    drift_start = 0.0
    last_ring = 0.0
    while True:
        title = active_title()
        now = time.time()
        if title and is_distracting(title):
            if not drift_start:
                drift_start = now
                print(f"drift started: {title[:80]}")
            drifted_min = (now - drift_start) / 60
            cooled = (now - last_ring) / 60 >= COOLDOWN_MINUTES
            if drifted_min >= DRIFT_MINUTES and cooled:
                nudge = (f"The user has been on '{title[:60]}' for "
                         f"{int(drifted_min)} minutes. Check in kindly and "
                         f"help them re-enter their task.")
                print(f"RING: {nudge}")
                asyncio.run(ring(nudge))
                last_ring = now
                drift_start = 0.0
        else:
            if drift_start:
                print("back on task")
            drift_start = 0.0
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
