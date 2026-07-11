"""Per-agent personal context — the convention every agent module uses.

Each agent has a personal markdown file at net_agents/context/<name>.md
that is loaded at startup and prepended to every LLM system prompt the
agent issues. Edit the .md, restart the agent — no code changes.

Lines of the form `@include <path>` (relative to the context dir) are
replaced by that file's contents, so a context file can pull in a large
shared runbook (e.g. the browser agent includes the operations guide the
user keeps at the project root).
"""
from __future__ import annotations

from pathlib import Path

CONTEXT_DIR = Path(__file__).resolve().parent / "context"


def load_context(agent_name: str) -> str:
    f = CONTEXT_DIR / f"{agent_name}.md"
    if not f.exists():
        return ""
    out: list[str] = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("@include "):
            inc = (CONTEXT_DIR / line.strip()[len("@include "):].strip()).resolve()
            if inc.exists():
                out.append(inc.read_text(encoding="utf-8"))
            else:
                out.append(f"(missing include: {inc})")
        else:
            out.append(line)
    return "\n".join(out).strip()
