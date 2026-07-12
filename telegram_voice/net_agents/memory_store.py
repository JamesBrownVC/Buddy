"""memory_store — a per-agent memory with bell-curve attention + a long-term layer.

Each agent gets its own store (state/memory/<agent>.jsonl). Recall ranks items by
RELEVANCE (embedding cosine similarity — a small RAG) x RECENCY (a Gaussian
"bell curve" around now, so what's recent gets the most attention) x IMPORTANCE.
Items flagged long-term don't decay — they're the durable layer.

Embeddings use OpenAI text-embedding-3-small; if unavailable it degrades to
keyword overlap, so memory never hard-fails.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import httpx

from net_agents.atomicio import locked

ROOT = Path(__file__).resolve().parent.parent
MEM_DIR = ROOT / "state" / "memory"
KEY = os.getenv("OPENAI_API_KEY", "")
SIGMA_DAYS = 7.0   # width of the recency bell-curve (matches the ADHD design)


def _embed(text: str):
    try:
        r = httpx.post("https://api.openai.com/v1/embeddings",
                       headers={"Authorization": f"Bearer {KEY}"},
                       json={"model": "text-embedding-3-small", "input": text[:2000]},
                       timeout=20)
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]
    except Exception:
        return None


def _cos(a, b) -> float:
    if not a or not b:
        return 0.0
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return s / (na * nb) if na and nb else 0.0


def _file(agent: str) -> Path:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    return MEM_DIR / f"{agent}.jsonl"


def remember(agent: str, text: str, importance: float = 0.5,
             longterm: bool = False, dedupe: bool = True) -> dict:
    text = text.strip()
    # Compute the embedding (a network call) BEFORE taking the lock — never hold
    # the file lock across I/O we don't control.
    rec = {"ts": int(time.time()), "text": text,
           "importance": max(0.0, min(1.0, float(importance))),
           "longterm": bool(longterm), "emb": _embed(text)}
    path = _file(agent)
    lock_path = path.with_suffix(path.suffix + ".lock")
    # Hold ONE lock across the dedupe-read AND the append, so two concurrent
    # writers (e.g. a replica + the bookkeeper agent) can't both pass the dedupe
    # check and double-write, and can't interleave bytes on a >4KB embedding line.
    try:
        with locked(lock_path):
            if dedupe and any(it.get("text") == text for it in _load(agent)):
                return rec
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass                            # memory is best-effort, never a hard fail
    return rec


def _load(agent: str) -> list[dict]:
    """Load an agent's memory, skipping any single corrupt line rather than
    discarding the whole file. A lone half-written line must never blank an
    agent's entire recall."""
    path = _file(agent)
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return []
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue                    # skip this line only, keep the rest
    return out


def recall(agent: str, query: str, k: int = 6, now: int | None = None) -> list[dict]:
    items = _load(agent)
    if not items:
        return []
    qv = _embed(query)
    qwords = set(query.lower().split())
    now = now or int(time.time())
    scored = []
    for it in items:
        if qv and it.get("emb"):
            rel = _cos(qv, it["emb"])
        else:
            tw = set(it["text"].lower().split())
            rel = len(qwords & tw) / max(1, len(qwords))
        if it.get("longterm"):
            recency = 1.0                                   # long-term never decays
        else:
            age_days = (now - it["ts"]) / 86400.0
            recency = math.exp(-(age_days ** 2) / (2 * SIGMA_DAYS ** 2))  # bell curve
        score = (0.15 + rel) * (0.3 + 0.7 * recency) * (0.5 + it.get("importance", 0.5))
        scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[:k]]
