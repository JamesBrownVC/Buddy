"""BROWSER agent — web tasks for the Hermes network.

Backend: psyb0t/docker-stealthy-auto-browse (stealth Firefox controlled
via JSON HTTP API, default http://127.0.0.1:8080/ — see
BROWSER_ASSISTANT_OPERATIONS.md, loaded as personal context).

Two modes, chosen automatically per request:
  CONTAINER mode — the stealth-browser API is reachable: an LLM tool-loop
    drives it action by action (goto/wait/get_text/eval/click...), guided
    by the operations guide in its context.
  FALLBACK mode — container down: keyless DuckDuckGo search + condense,
    so research requests never dead-end.

Contract (same as every agent): POST /ask {"message", "from",
"request_id"?, "reply_to"?} -> {"reply": ...}.

Run:  .venv\\Scripts\\python.exe -m uvicorn net_agents.browser:app --port 9103
Env:  OPENAI_API_KEY, BROWSER_API (default http://127.0.0.1:8080),
      BROWSER_MODEL (default gpt-4o)
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
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
MODEL = os.getenv("BROWSER_MODEL", "gpt-4o")
BROWSER_API = os.getenv("BROWSER_API", "http://127.0.0.1:8080").rstrip("/")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) hermes-agent/1.0"}
MAX_STEPS = 12

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("browser")

from net_agents.agent_context import load_context
from net_agents.failure_log import log_failure  # noqa: E402
PERSONAL_CONTEXT = load_context("browser")  # persona + Buddy README + ops guide

app = FastAPI(title="browser agent")


# ── container mode: LLM tool-loop over the stealth-browser HTTP API ────
def container_up() -> bool:
    try:
        return httpx.get(f"{BROWSER_API}/health", timeout=3).text.strip() == "ok"
    except Exception:
        return False


def browser_action(payload: dict) -> str:
    """One JSON command to the stealth-browser API (params at root, per
    the ops guide). Returns the JSON result as text for the LLM."""
    try:
        r = httpx.post(f"{BROWSER_API}/", json=payload, timeout=90)
        return r.text[:6000]
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


CONTAINER_TOOLS = [{
    "type": "function", "function": {
        "name": "browser_action",
        "description": "Send ONE JSON command to the stealth-browser HTTP "
                       "API. Params go at the ROOT next to 'action' (e.g. "
                       "{\"action\":\"goto\",\"url\":...,\"wait_until\":"
                       "\"domcontentloaded\"}). Prefer run_script for "
                       "dependent steps. Follow your operations guide.",
        "parameters": {"type": "object", "properties": {
            "payload": {"type": "object",
                        "description": "the full JSON body, action at root"}},
            "required": ["payload"]}}}]

CONTAINER_SYSTEM = (
    "Complete the requested web task using the browser_action tool, "
    "strictly following your operations guide (fewest state-changing "
    "operations; list_tabs once first; reuse or create a tab, never hijack "
    "existing ones; wait for state, not time; get_text before anything "
    "visual; validate outcomes; no consequential actions without explicit "
    "authorization in the request). When done, reply with the answer in "
    "2-5 plain sentences plus 'source: <url>'. If the task cannot be "
    "completed, say exactly what blocked you."
)


def run_container_task(task: str) -> str:
    messages = [
        {"role": "system", "content": PERSONAL_CONTEXT + "\n\n" + CONTAINER_SYSTEM},
        {"role": "user", "content": task},
    ]
    for _ in range(MAX_STEPS):
        try:
            r = httpx.post("https://api.openai.com/v1/chat/completions",
                           headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                           json={"model": MODEL, "temperature": 0.2,
                                 "messages": messages, "tools": CONTAINER_TOOLS},
                           timeout=120)
            r.raise_for_status()
            m = r.json()["choices"][0]["message"]
        except Exception as e:
            log.warning("llm failed: %s", e)
            return f"Browser LLM failed: {e}"
        messages.append(m)
        calls = m.get("tool_calls") or []
        if not calls:
            return (m.get("content") or "done").strip()
        for c in calls:
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
                payload = args.get("payload", args)
            except Exception:
                payload = {}
            result = browser_action(payload)
            log.info("action %s -> %s", str(payload.get("action")), result[:120])
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": result})
    return "Step budget exhausted; ask me to continue with a narrower task."


# ── fallback mode: keyless DuckDuckGo search + condense ────────────────
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
    return [{"title": strip(t), "url": href,
             "snippet": strip(snippets[i]) if i < len(snippets) else ""}
            for i, (href, t) in enumerate(titles[:n])]


def condense(question: str, results: list[dict]) -> str:
    listing = "\n".join(f"- {r['title']}: {r['snippet']} ({r['url']})"
                        for r in results)
    reply = _chain_chat(
        "You are the Browser agent (fallback search mode). Answer the "
        "question from the search results in 2-4 plain sentences, then one "
        "line 'source: <best url>'. If the results don't answer it, say so.",
        f"Question: {question}\n\nSearch results:\n{listing}")
    return reply or f"Top results for '{question}':\n{listing}"


def fallback_search(q: str) -> str:
    try:
        results = ddg_search(q)
    except Exception as e:
        return f"Search failed: {e}"
    if not results:
        return f"No web results found for: {q}"
    return condense(q, results)


# ── /ask ────────────────────────────────────────────────────────────────
class Ask(BaseModel):
    message: str


# PRIMARY: this agent's own Hermes instance (browserbrain, :8644).
# FALLBACK: direct gpt-5.6-terra. Short Hermes timeout keeps voice calls snappy.
LLM_BACKENDS = [
    {"name": "hermes", "base": os.getenv("BROWSER_BRAIN_URL", "http://127.0.0.1:8644/v1"),
     "key": os.getenv("BROWSER_BRAIN_KEY", "browserbrain-local"),
     "model": "hermes-agent", "gpt5": False, "timeout": 18},
    {"name": "terra", "base": "https://api.openai.com/v1",
     "key": OPENAI_KEY, "model": "gpt-5.6-terra", "gpt5": True, "timeout": 30},
]

_CONDENSE_SYSTEM = (
    "You are the Browser agent. From the text of a web search-results page, "
    "answer the user's question in 2-4 plain spoken sentences, then one line "
    "'source: <best url>'. If the text is thin, give the best summary you "
    "can — never say you failed."
)


def _chain_chat(system: str, user: str, max_out: int = 220) -> str | None:
    """Hermes-primary, terra-fallback chat call shared by condense paths."""
    for b in LLM_BACKENDS:
        if not b["key"]:
            continue
        body = {"model": b["model"],
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        if b["gpt5"]:
            body["reasoning_effort"] = "none"
            body["max_completion_tokens"] = max_out
        else:
            body["max_tokens"] = max_out       # Hermes: standard fields only
        try:
            r = httpx.post(f"{b['base']}/chat/completions",
                           headers={"Authorization": f"Bearer {b['key']}"},
                           json=body, timeout=b["timeout"])
            r.raise_for_status()
            content = (r.json()["choices"][0]["message"].get("content") or "").strip()
            if content:
                log.info("browser llm via %s", b["name"])
                return content
        except Exception as e:
            log.warning("browser %s failed (%s); trying next", b["name"], e)
    return None


def condense_text(question: str, text: str, url: str) -> str:
    """Turn a fetched page's text into a short sourced answer."""
    if not text:
        return f"I looked that up — see {url}"
    reply = _chain_chat(_CONDENSE_SYSTEM,
                        f"Question: {question}\n\nPage text:\n{text}")
    return reply or f"I searched '{question}' — see {url}"


def container_lookup(q: str) -> str:
    """Deterministic, VISIBLE lookup: drive the real (stealth) browser to a
    search-results page, read it, condense. No LLM tab-management loop, so it
    never gets stuck 'opening a new tab' on the 2nd+ call — and it always shows
    on the live noVNC screen. Raises on container trouble so the caller can log
    a repairable failure instead of silently degrading."""
    url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(q)
    goto = browser_action({"action": "goto", "url": url,
                           "wait_until": "domcontentloaded"})
    try:
        gj = json.loads(goto)
        if isinstance(gj, dict) and gj.get("success") is False:
            raise RuntimeError(f"goto failed: {gj.get('error') or goto[:120]}")
    except (ValueError, TypeError):
        pass  # non-JSON goto response — let get_text decide
    raw = browser_action({"action": "get_text"})
    try:
        page = json.loads(raw)
        text = (page.get("data") or {}).get("text") or ""
    except Exception:
        text = raw or ""
    if not text.strip():
        raise RuntimeError("empty page text from stealth browser")
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", text)).strip()[:6000]
    return condense_text(q, text, url)


@app.post("/ask")
def ask(a: Ask) -> dict:
    q = a.message.strip()
    # ALWAYS prefer the visible stealth browser. Every degrade to the invisible
    # text fallback is logged as a repairable failure so the Repair agent can
    # fix the browser — we never silently switch to DuckDuckGo.
    up = container_up()
    if up:
        log.info("visible lookup: %s", q[:120])
        try:
            return {"reply": container_lookup(q)}
        except Exception as e:
            log.warning("stealth browser failed (%s); logging for repair", e)
            log_failure("browser", "container_lookup_failed", str(e),
                        {"query": q[:200], "browser_api": BROWSER_API})
    else:
        log.warning("stealth browser DOWN; logging for repair")
        log_failure("browser", "container_down",
                    "container_up() is False — /health not 'ok'",
                    {"query": q[:200], "browser_api": BROWSER_API})
    return {"reply": fallback_search(q)}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "agent": "browser",
            "backend": "container" if container_up() else "fallback-search",
            "context_chars": len(PERSONAL_CONTEXT)}
