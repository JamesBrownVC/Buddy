"""security_events — the mesh's tamper-evident security journal.

Every injection-guard signal (a suspicious pre-filter hit, a honeytoken trip, a
lockdown transition) is appended here as one JSON line. Append is atomic and
lock-guarded so concurrent hub workers never corrupt the journal — the exact
failure an auto-kill-on-trip design would cause mid-write.

Records are data for the Audit agent, never control flow: writing one never
raises, and nothing here can act on the event.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from net_agents.atomicio import atomic_append

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "state" / "security_events.jsonl"


def record(kind: str, detail: dict | None = None) -> dict:
    """Append one security event. `kind` is a short slug
    (suspicious | honeytoken_trip | lockdown_engaged | lockdown_cleared).
    Returns the record (never raises)."""
    rec = {"ts": int(time.time()), "kind": kind, **(detail or {})}
    atomic_append(EVENTS, json.dumps(rec, ensure_ascii=False))
    return rec


def recent(limit: int = 50) -> list[dict]:
    """Most-recent security events, newest first (for the Audit agent)."""
    try:
        lines = EVENTS.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out
