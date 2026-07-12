"""lockdown — a non-destructive containment state machine for injection trips.

Design constraint (deliberately overriding "down the system on a canary hit"):
a tripwire must CONTAIN, never self-destruct. Auto-killing the mesh on a trip
would hand an attacker a one-string kill switch, because the browser/personal
agents ingest untrusted web/email text. So the worst this module can ever do is
REFUSE to route to a high-power agent — it never touches a process.

Semantics:
  * A honeytoken trip is quarantined per-request by the caller (zero blast
    radius). This module only tracks REPEATED trips.
  * >= TRIP_THRESHOLD trips inside WINDOW_S engages lockdown.
  * While locked, routing to a HIGH_POWER agent is refused; every low-power
    agent keeps serving. Lockdown auto-expires after TTL_S or on an explicit
    authenticated reset().
  * User alerts are coalesced to one per transition (engage/clear), never one
    per trip — one-alert-per-trip is itself an alert-fatigue DoS.

The functions are PURE (state in, state out) so they unit-test with a fake clock
and no I/O. Persistence (atomic load/save of lockdown.json) is separate.
"""
from __future__ import annotations

import json
from pathlib import Path

from net_agents.atomicio import atomic_write

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "lockdown.json"

TRIP_THRESHOLD = 3          # trips within the window that engage lockdown
WINDOW_S = 600              # sliding window for counting trips (10 min)
TTL_S = 3600               # lockdown auto-expires after this (1 h)
ALERT_COOLDOWN_S = 300     # min seconds between user alerts (anti alert-fatigue)

# Agents that can act on the user's behalf or touch private data. Routing to
# these is refused while locked; everything else stays available. Fail-closed:
# builder-generated agents are treated as high-power by the hub gate.
HIGH_POWER = {"browser", "personal", "bookkeeper", "orchestrator",
              "builder", "toolsmith", "repair", "audit"}


def _blank() -> dict:
    return {"active": False, "since": 0, "trips": [], "window_start": 0,
            "engaged_alerted": False, "last_alert": 0}


def should_alert(state: dict, now: int) -> bool:
    """Rate-limit user alerts: at most one per ALERT_COOLDOWN_S. One-alert-per-trip
    would itself be an alert-fatigue DoS."""
    return (now - int((state or {}).get("last_alert", 0))) >= ALERT_COOLDOWN_S


def mark_alert(state: dict, now: int) -> dict:
    s = dict(state or _blank())
    s["last_alert"] = now
    return s


def register_trip(state: dict, now: int) -> tuple[dict, bool]:
    """Record one honeytoken trip. Returns (new_state, engaged_now) where
    engaged_now is True only on the transition into lockdown (for a single
    coalesced alert)."""
    s = dict(state or _blank())
    trips = [t for t in s.get("trips", []) if now - t < WINDOW_S]
    trips.append(now)
    s["trips"] = trips
    engaged_now = False
    # Use is_locked (honours TTL) rather than the raw 'active' flag: a lockdown
    # whose TTL has expired but whose flag is still True must be able to
    # re-engage on a fresh wave of trips.
    if not is_locked(s, now) and len(trips) >= TRIP_THRESHOLD:
        s["active"] = True
        s["since"] = now
        s["engaged_alerted"] = False
        engaged_now = True
    return s, engaged_now


def is_locked(state: dict, now: int) -> bool:
    """Whether lockdown is currently active (honouring TTL expiry)."""
    s = state or {}
    if not s.get("active"):
        return False
    return (now - int(s.get("since", 0))) < TTL_S


def should_refuse(state: dict, agent: str, now: int,
                  high_power: set[str] | None = None) -> bool:
    """True if routing to `agent` must be refused right now. Only high-power
    agents are ever refused; low-power agents always route."""
    if not is_locked(state, now):
        return False
    hp = high_power if high_power is not None else HIGH_POWER
    return (agent or "").strip().lower() in hp


def clear_if_expired(state: dict, now: int) -> tuple[dict, bool]:
    """Auto-clear an expired lockdown. Returns (new_state, cleared_now)."""
    s = dict(state or _blank())
    if s.get("active") and (now - int(s.get("since", 0))) >= TTL_S:
        s["active"] = False
        s["trips"] = []
        return s, True
    return s, False


def reset(state: dict | None = None) -> dict:
    """Explicit authenticated reset — clears lockdown entirely."""
    return _blank()


def mark_alerted(state: dict) -> dict:
    """Record that the engage alert for the current lockdown has been sent, so
    repeated trips don't re-alert."""
    s = dict(state or _blank())
    s["engaged_alerted"] = True
    return s


# ── persistence (atomic; never raises into the request path) ──────────────────

def load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _blank()


def save(state: dict) -> None:
    try:
        atomic_write(STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2))
    except Exception:
        pass
