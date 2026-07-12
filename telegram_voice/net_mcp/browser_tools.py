"""browser_tools — MCP tools that drive the VISIBLE stealth browser.

Attached to the browser agent's Hermes profile so that Hermes agent can, of its
own accord, search and read the live web on the real Camoufox container (visible
on noVNC :5900). It never uses an invisible fallback silently — a container
failure is logged for the repair agent.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse

import httpx
from mcp.server.fastmcp import FastMCP

BROWSER_API = os.getenv("BROWSER_API", "http://127.0.0.1:8080").rstrip("/")

mcp = FastMCP("browser_tools")


def _log_fail(kind: str, detail: str, ctx: dict) -> None:
    try:
        import sys
        sys.path.insert(0, os.getenv("PYTHONPATH", "."))
        from net_agents.failure_log import log_failure
        log_failure("browser", kind, detail, ctx)
    except Exception:
        pass


def _action(payload: dict) -> dict:
    r = httpx.post(f"{BROWSER_API}/", json=payload, timeout=90)
    try:
        return r.json()
    except Exception:
        return {"success": False, "error": r.text[:200]}


@mcp.tool()
def web_search(query: str) -> str:
    """Search the live web on the real stealth browser and return the results
    page text. The search is VISIBLE on the noVNC screen. Use this for any
    factual lookup, then summarise the returned text for the user."""
    url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    goto = _action({"action": "goto", "url": url, "wait_until": "domcontentloaded"})
    if isinstance(goto, dict) and goto.get("success") is False:
        _log_fail("container_lookup_failed", str(goto.get("error")), {"query": query})
        return f"STEALTH BROWSER ERROR (ask the repair agent to fix it): {goto.get('error')}"
    page = _action({"action": "get_text"})
    text = (page.get("data") or {}).get("text", "") if isinstance(page, dict) else ""
    if not text.strip():
        _log_fail("container_down", "empty page text", {"query": query})
        return "STEALTH BROWSER returned no text (ask the repair agent to fix it)."
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", text)).strip()[:6000]
    return f"Search results for '{query}' (source: {url}):\n\n{text}"


@mcp.tool()
def open_url(url: str) -> str:
    """Open a specific URL on the stealth browser and return the page text.
    Use this to open a web app the user is signed into (WhatsApp Web, Gmail,
    Slack, Notion, a calendar, …) and read it, then click/type to act on it."""
    goto = _action({"action": "goto", "url": url, "wait_until": "domcontentloaded"})
    if isinstance(goto, dict) and goto.get("success") is False:
        _log_fail("container_lookup_failed", str(goto.get("error")), {"url": url})
        return f"STEALTH BROWSER ERROR: {goto.get('error')}"
    page = _action({"action": "get_text"})
    text = (page.get("data") or {}).get("text", "") if isinstance(page, dict) else ""
    return f"{url}:\n\n{text.strip()[:6000]}" if text.strip() else "no text on page"


@mcp.tool()
def read_page() -> str:
    """Read the text of the page currently open in the stealth browser (after a
    click/type, or to check state). Does not navigate."""
    page = _action({"action": "get_text"})
    text = (page.get("data") or {}).get("text", "") if isinstance(page, dict) else ""
    return text.strip()[:6000] or "no text on the current page"


@mcp.tool()
def click(selector: str) -> str:
    """Click an element on the current page by CSS selector (e.g. a button, a
    link, a chat, a compose button). Then call read_page to see the result."""
    r = _action({"action": "click", "selector": selector})
    ok = isinstance(r, dict) and r.get("success") is not False
    return f"clicked {selector}" if ok else f"click failed: {r.get('error') if isinstance(r, dict) else r}"


@mcp.tool()
def type_text(selector: str, text: str) -> str:
    """Type text into an input/textarea on the current page by CSS selector
    (e.g. a search box, a message field). Combine with click to submit."""
    r = _action({"action": "type", "selector": selector, "text": text})
    ok = isinstance(r, dict) and r.get("success") is not False
    return f"typed into {selector}" if ok else f"type failed: {r.get('error') if isinstance(r, dict) else r}"


if __name__ == "__main__":
    mcp.run()
