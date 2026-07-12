"""Shared structured failure log for the Buddy agent network.

Every agent records failures here as JSON lines so the Repair agent can read,
retrieve (its small local RAG), diagnose, and fix them. One append-only file:
``state/failures.jsonl``. Keep it dependency-free and crash-proof — logging a
failure must never itself raise.

    from net_agents.failure_log import log_failure
    log_failure("browser", "container_unavailable",
                "goto returned success=false", {"query": q})
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

_STATE = Path(__file__).resolve().parent.parent / "state"
_FILE = _STATE / "failures.jsonl"


def log_failure(agent: str, kind: str, detail: str,
                context: dict | None = None) -> None:
    """Append one failure record. Never raises."""
    try:
        _STATE.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "epoch": int(time.time()),
            "agent": agent,
            "kind": kind,
            "detail": str(detail)[:500],
            "context": context or {},
            "pid": os.getpid(),
        }
        with open(_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging must never break the caller


def recent_failures(limit: int = 50) -> list[dict]:
    """Most-recent failures, newest first. Never raises."""
    try:
        if not _FILE.exists():
            return []
        lines = _FILE.read_text(encoding="utf-8").splitlines()
        out = []
        for ln in reversed(lines[-limit * 2:]):
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []
