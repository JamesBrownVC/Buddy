"""prompt_snapshot — a tamper-evident copy of every agent's system prompt.

At build/startup each agent's composed persona (SOUL) is snapshotted to
state/prompts/<agent>.md with a trailing sha256. The Audit agent reads these to
review what each agent was actually told, and to detect DRIFT — a SOUL file that
has changed (e.g. an injected instruction) shows up as a hash mismatch against
its snapshot. Prompts can contain secrets, so snapshots live under state/ (which
is gitignored) and only hashes — never prompt text — are logged.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from net_agents.atomicio import atomic_write

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "state" / "prompts"

_MARK = "\n\n<!-- sha256:"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot(agent: str, prompt: str) -> str:
    """Write/refresh an agent's prompt snapshot. Returns the sha256."""
    h = _hash(prompt)
    atomic_write(PROMPTS / f"{agent}.md", f"{prompt}{_MARK}{h} -->\n")
    return h


def list_agents() -> list[str]:
    try:
        return sorted(p.stem for p in PROMPTS.glob("*.md"))
    except Exception:
        return []


def read(agent: str) -> str:
    try:
        return (PROMPTS / f"{agent}.md").read_text(encoding="utf-8")
    except Exception:
        return ""


def _stored_hash(agent: str) -> str:
    text = read(agent)
    if _MARK.strip() in text:
        tail = text.rsplit("sha256:", 1)[-1]
        return tail.split(" ", 1)[0].strip()
    return ""


def drift(agent: str, live_prompt: str) -> dict:
    """Compare a live prompt against the stored snapshot. Returns
    {agent, changed, stored, live}. `changed` True => the prompt was altered
    since it was snapshotted (possible tampering)."""
    stored = _stored_hash(agent)
    live = _hash(live_prompt)
    return {"agent": agent, "changed": bool(stored) and stored != live,
            "stored": stored, "live": live}
