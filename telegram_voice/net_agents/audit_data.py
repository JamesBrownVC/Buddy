"""audit_data — read + summarise the task log for the Audit agent (pure logic).

Every agent action is logged (by the hub) to state/task_log.jsonl as
{ts, level: macro|micro, from, agent, ask, reply, ms, ok}. This module turns
that into evidence the Audit agent reasons over.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_LOG = ROOT / "state" / "task_log.jsonl"


def read_tasks(limit: int = 40) -> list[dict]:
    """Most-recent task records, newest first."""
    try:
        lines = TASK_LOG.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def performance_summary(window: int = 200) -> dict:
    """Per-agent stats over the recent window: volume, failure rate, avg/max
    latency, and the tasks that look worst (failed, empty, or very slow)."""
    tasks = read_tasks(window)
    per = defaultdict(lambda: {"n": 0, "fail": 0, "ms": []})
    worst = []
    for t in tasks:
        a = t.get("agent", "?")
        s = per[a]
        s["n"] += 1
        ms = int(t.get("ms", 0))
        s["ms"].append(ms)
        bad = (not t.get("ok")) or "unavailable" in (t.get("reply", "").lower()) \
            or "error" in (t.get("reply", "").lower()) or "couldn't" in (t.get("reply", "").lower())
        if bad:
            s["fail"] += 1
        if bad or ms > 25000:
            worst.append({"agent": a, "from": t.get("from"), "ms": ms,
                          "ask": t.get("ask", "")[:120], "reply": t.get("reply", "")[:160]})
    agents = {}
    for a, s in per.items():
        msl = s["ms"] or [0]
        agents[a] = {"tasks": s["n"], "failures": s["fail"],
                     "fail_rate": round(s["fail"] / s["n"], 2) if s["n"] else 0,
                     "avg_ms": int(sum(msl) / len(msl)), "max_ms": max(msl)}
    return {"window": len(tasks), "per_agent": agents, "worst": worst[:12]}
