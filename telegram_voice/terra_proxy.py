"""terra_proxy — make gpt-5.6-terra usable as a Hermes inference backend.

Hermes' request builder emits params that gpt-5.6-terra rejects over
/v1/chat/completions (``think``, ``max_tokens``, arbitrary ``temperature``,
and ``reasoning_effort`` values other than ``none`` alongside tools). This
proxy sits between a Hermes instance and the OpenAI API, sanitises the body
so gpt-5.6-terra accepts it, and streams the response straight back.

    Hermes (openai-direct base_url = http://127.0.0.1:8650/v1)
        -> terra_proxy (sanitise) -> https://api.openai.com/v1

The caller's Authorization header (the real OpenAI key) is forwarded as-is.

Run:  .venv/bin/python -m uvicorn terra_proxy:app --port 8650
"""
from __future__ import annotations

import hashlib
import json
import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

UPSTREAM = "https://api.openai.com/v1"
FORCE_MODEL = "gpt-5.6-terra"
# Params gpt-5.6-terra rejects outright — drop them.
# NOTE: 'tools'/'tool_choice' are deliberately NOT dropped — the router's
# honeytoken tripwire depends on them surviving the proxy. See test_proxy.
DROP = {"think", "thinking", "temperature", "top_p", "presence_penalty",
        "frequency_penalty", "logit_bias", "reasoning"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("terra_proxy")

app = FastAPI(title="terra proxy")


def _system_text(messages) -> str:
    """The leading system message's text, if any — the stable cacheable prefix."""
    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
        m0 = messages[0]
        if m0.get("role") == "system":
            c = m0.get("content", "")
            return c if isinstance(c, str) else json.dumps(c, sort_keys=True)
    return ""


def sanitise(body: dict) -> dict:
    b = {k: v for k, v in body.items() if k not in DROP}
    b["model"] = FORCE_MODEL
    # max_tokens -> max_completion_tokens (gpt-5.x requirement)
    if "max_tokens" in b:
        b.setdefault("max_completion_tokens", b.pop("max_tokens"))
    else:
        b.pop("max_tokens", None)
    # gpt-5.6-terra: tools only allowed with reasoning_effort == "none"
    b["reasoning_effort"] = "none"
    # Prompt caching: a stable per-agent key (hash of the system prompt) routes
    # repeat calls to the same cache node. It auto-rotates if the persona changes
    # and never contains the prompt itself. Only set when a system prompt exists.
    sys_text = _system_text(b.get("messages"))
    if sys_text:
        b.setdefault("prompt_cache_key",
                     "buddy-" + hashlib.sha256(sys_text.encode("utf-8")).hexdigest()[:16])
    # ask upstream to report token usage on the streamed path too
    if b.get("stream"):
        so = b.get("stream_options") or {}
        so.setdefault("include_usage", True)
        b["stream_options"] = so
    return b


def _log_cache(body: dict, response: dict) -> None:
    """Log ONLY token counts + the cache key — never prompt/persona/secrets.
    This is the ground truth that caching actually fires."""
    try:
        u = response.get("usage") or {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        prompt = u.get("prompt_tokens", 0)
        if prompt:
            log.info("cache key=%s prompt=%d cached=%d (%.0f%% hit)",
                     body.get("prompt_cache_key", "-"), prompt, cached,
                     100.0 * cached / prompt)
    except Exception:
        pass


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_completions(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw)
    except Exception:
        body = {}
    body = sanitise(body)
    auth = request.headers.get("authorization", "")
    headers = {"Authorization": auth, "Content-Type": "application/json"}
    stream = bool(body.get("stream"))
    url = f"{UPSTREAM}/chat/completions"

    if stream:
        async def gen():
            async with httpx.AsyncClient(timeout=180) as client:
                async with client.stream("POST", url, headers=headers,
                                         json=body) as r:
                    async for chunk in r.aiter_raw():
                        yield chunk
        return StreamingResponse(gen(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(url, headers=headers, json=body)
    payload = r.json()
    if r.status_code == 200:
        _log_cache(body, payload)
    return JSONResponse(status_code=r.status_code, content=payload)


@app.get("/v1/models")
@app.get("/health")
async def health():
    return {"ok": True, "proxy": "terra", "forces_model": FORCE_MODEL}
