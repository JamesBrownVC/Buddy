#!/usr/bin/env python3
"""
demo_pump.py — Buddy demo "liveliness" pump.

Makes the on-stage demo look ALIVE: it gently drives the already-running
stealth browser through a rotation of real, safe, visually-interesting pages
(so the noVNC "Live Browser" tab visibly loads pages on a loop) and posts
believable ADHD-assistant wins/facts to the hub (so memory/activity counters
tick up). One clean status line is printed per action.

HOW TO RUN (from the telegram_voice/ folder):
    .venv/bin/python demo_pump.py

HOW TO STOP:
    Ctrl+C  (clean shutdown, no state left behind)

SAFE / IDEMPOTENT: talks ONLY to already-running LOCAL services
(stealth browser API on :8080, hub on :8484). It creates no files, installs
nothing, and every request is wrapped in try/except so a momentarily-busy
service just gets skipped — the loop never crashes. Stdlib only.
"""

import json
import random
import time
import urllib.request
from datetime import datetime

BROWSER_API = "http://127.0.0.1:8080"      # stealth browser (Camoufox in Docker)
HUB = "http://127.0.0.1:8484"              # FastAPI hub

# Real, safe, visually-interesting pages to rotate the live browser through.
URLS = [
    "https://example.com",
    "https://en.wikipedia.org/wiki/Executive_functions",
    "https://en.wikipedia.org/wiki/Attention",
    "https://en.wikipedia.org/wiki/Time_management",
    "https://news.ycombinator.com",
    "https://weather.com",
]

# Believable "user completed X" wins for the activity feed.
WINS = [
    "User completed: replied to Sam's email",
    "User completed: sent the invoice to Acme",
    "User completed: 25-min focus sprint on the deck",
    "User completed: booked the standup room",
    "User completed: paid the electricity bill",
    "User completed: called the dentist back",
    "User completed: submitted the expense report",
]

# Believable captured facts for memory.
FACTS = [
    "Captured: dentist appointment Thursday 3pm",
    "Captured: Mom's birthday is next Saturday",
    "Captured: prefers deep-work mornings, meetings after 2pm",
    "Captured: standup moved to 9:45am on Fridays",
    "Captured: renew car insurance before the 28th",
    "Captured: Sam prefers Slack over email for quick asks",
    "Captured: gym class is Tuesday and Thursday at 6pm",
]


def _post(url, payload, timeout=12):
    """POST json, return decoded dict or None. Never raises."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return None


def _log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def drive_browser():
    """Navigate the stealth browser to a random URL, then read its title."""
    url = random.choice(URLS)
    nav = _post(BROWSER_API, {"action": "goto", "url": url}, timeout=25)
    if not nav or not nav.get("success"):
        _log(f"browser  · skipped {url} (busy)")
        return
    title = ""
    got = _post(BROWSER_API, {"action": "get_text"}, timeout=15)
    if got and got.get("success"):
        title = (got.get("data") or {}).get("text", "")[:48].replace("\n", " ").strip()
    _log(f"browser  · loaded {url}" + (f"  ->  \"{title}...\"" if title else ""))


def post_win():
    what = random.choice(WINS)
    if _post(f"{HUB}/log_win", {"what": what}) is not None:
        _log(f"win      · {what}")
    else:
        _log("win      · skipped (hub busy)")


def post_fact():
    fact = random.choice(FACTS)
    if _post(f"{HUB}/remember", {"fact": fact}) is not None:
        _log(f"memory   · {fact}")
    else:
        _log("memory   · skipped (hub busy)")


def main():
    _log("demo_pump started — driving live browser + hub. Ctrl+C to stop.")
    beat = 0
    try:
        while True:
            drive_browser()          # ~1 real navigation per cycle
            if beat % 2 == 0:
                post_win()           # a win every other cycle
            if beat % 3 == 1:
                post_fact()          # a fact roughly every third cycle
            beat += 1
            time.sleep(random.uniform(15, 20))   # gentle cadence, not hammering
    except KeyboardInterrupt:
        _log("demo_pump stopped. Bye.")


if __name__ == "__main__":
    main()
