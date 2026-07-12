"""memory_tools — MCP tools over the shared bookkeeper memory store.

Attached to the bookkeeper agent's Hermes profile so that Hermes agent
autonomously captures, recalls, and completes items in the same
net_agents/state/bookkeeper.json the dashboard reads. Items:
  {id, text, status: active|done, date, deferred, longterm, created}
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

STATE = Path(os.getenv("BUDDY_STATE",
             str(Path(__file__).resolve().parent.parent / "net_agents" / "state")))
FILE = STATE / "bookkeeper.json"

mcp = FastMCP("memory_tools")


def _load() -> dict:
    try:
        d = json.loads(FILE.read_text())
        d.setdefault("working", []); d.setdefault("longterm", [])
        return d
    except Exception:
        return {"working": [], "longterm": []}


def _save(d: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False))


def _new_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000) % 100000}"


@mcp.tool()
def remember(text: str, date: str = "", longterm: bool = False) -> str:
    """Store something for the user. `text` is the item; `date` optional (e.g.
    'Thu', '2026-07-14', 'today 16:00'); set longterm=true for scheduled/future
    commitments, false for current working-memory tasks."""
    d = _load()
    item = {"id": _new_id("lt" if longterm else "wk"), "text": text.strip(),
            "status": "active", "date": date.strip(), "deferred": False,
            "longterm": bool(longterm),
            "created": time.strftime("%Y-%m-%d %H:%M")}
    (d["longterm"] if longterm else d["working"]).append(item)
    _save(d)
    return f"stored [{item['id']}]: {item['text']}"


@mcp.tool()
def recall(query: str = "") -> str:
    """Return the user's current memory — active working items and long-term /
    scheduled items. Optional `query` filters by substring."""
    d = _load()
    q = query.strip().lower()
    def fmt(items):
        out = []
        for it in items:
            if it.get("status") != "active":
                continue
            if q and q not in it.get("text", "").lower():
                continue
            dt = it.get("date") or "-"
            out.append(f"- {it['text']} (date {dt}) [{it['id']}]")
        return out
    wk = fmt(d["working"]); lt = fmt(d["longterm"])
    parts = []
    if wk: parts.append("Working memory:\n" + "\n".join(wk))
    if lt: parts.append("Long-term / scheduled:\n" + "\n".join(lt))
    return "\n\n".join(parts) or "nothing in memory yet"


@mcp.tool()
def complete(item_id: str) -> str:
    """Mark a memory item done by its id (e.g. 'wk-12345')."""
    d = _load()
    for key in ("working", "longterm"):
        for it in d[key]:
            if it.get("id") == item_id:
                it["status"] = "done"
                _save(d)
                return f"marked done: {it['text']}"
    return f"no item with id {item_id}"


if __name__ == "__main__":
    mcp.run()
