"""BROWSER agent — web lookups for the Hermes network.

Self-contained module. Other agents (book-keeper, the voice agent) send it
a question as text; it searches the web (DuckDuckGo, keyless), reads the
result snippets, and replies with a condensed answer + sources.

Run:  .venv\\Scripts\\python.exe -m uvicorn net_agents.browser:app --port 9103
Env:  OPENAI_API_KEY (optional — without it, returns raw top results)
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) hermes-agent/1.0"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("browser")

from net_agents.agent_context import load_context  # noqa: E402
PERSONAL_CONTEXT = load_context("browser")  # includes the operations guide

app = FastAPI(title="browser agent")


def ddg_search(query: str, n: int = 5) -> list[dict]:
    r = httpx.get("https://html.duckduckgo.com/html/",
                  params={"q": query}, headers=UA, timeout=20,
                  follow_redirects=True)
    r.raise_for_status()
    html = r.text
    titles = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)
    snippets = re.findall(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
    strip = lambda s: re.sub(r"<[^>]+>", "", s).strip()
    out = []
    for i, (href, title) in enumerate(titles[:n]):
        out.append({"title": strip(title),
                    "url": href,
                    "snippet": strip(snippets[i]) if i < len(snippets) else ""})
    return out


def condense(question: str, results: list[dict]) -> str:
    listing = "\n".join(f"- {r['title']}: {r['snippet']} ({r['url']})"
                        for r in results)
    if not OPENAI_KEY:
        return f"Top results for '{question}':\n{listing}"
    try:
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            json={"model": MODEL, "temperature": 0.2, "max_tokens": 220,
                  "messages": [
                      {"role": "system", "content":
                       (PERSONAL_CONTEXT + "\n\n" if PERSONAL_CONTEXT else "") +
                       "Answer the question from the search results in 2-4 "
                       "plain sentences, then one line 'source: <best url>'. "
                       "If the results don't answer it, say so."},
                      {"role": "user", "content":
                       f"Question: {question}\n\nSearch results:\n{listing}"}]},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("condense failed: %s", e)
        return f"Top results for '{question}':\n{listing}"


class Ask(BaseModel):
    message: str


@app.post("/ask")
def ask(a: Ask) -> dict:
    q = a.message.strip()
    log.info("lookup: %s", q[:120])
    try:
        results = ddg_search(q)
    except Exception as e:
        return {"reply": f"Search failed: {e}"}
    if not results:
        return {"reply": f"No web results found for: {q}"}
    return {"reply": condense(q, results)}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "agent": "browser"}
