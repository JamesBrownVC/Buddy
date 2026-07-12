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

import json
import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

UPSTREAM = "https://api.openai.com/v1"
FORCE_MODEL = "gpt-5.6-terra"
# Params gpt-5.6-terra rejects outright — drop them.
DROP = {"think", "thinking", "temperature", "top_p", "presence_penalty",
        "frequency_penalty", "logit_bias", "reasoning"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("terra_proxy")

app = FastAPI(title="terra proxy")


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
    return b


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
    return JSONResponse(status_code=r.status_code, content=r.json())


@app.get("/v1/models")
@app.get("/health")
async def health():
    return {"ok": True, "proxy": "terra", "forces_model": FORCE_MODEL}
