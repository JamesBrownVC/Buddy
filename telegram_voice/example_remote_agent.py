"""Drop-in template for an agent hosted on your VPS / Mac mini.

Copy this file to the remote box, `pip install fastapi uvicorn httpx`, set the
two env vars, run it — it's now a full member of the Hermes network:

  IN  — Hermes messages it mid-call:   POST /ask   {"message": ..., "from": ...}
  IN  — it receives the event stream:  POST /events (after subscribing)
  OUT — it can drive Hermes:           POST {HUB}/webhook/ring   (make Hermes call the user)
                                       POST {HUB}/webhook/event  (publish to the stream)

Env:
  HERMES_HUB   = https://<tunnel-or-hub-host>          (the hub's public URL)
  HERMES_SECRET= <HUB_SECRET from telegram_voice/.env>

Run:
  uvicorn example_remote_agent:app --host 0.0.0.0 --port 9101
Then register it in agents.json on the hub machine:
  "ops": {"type": "http", "url": "http://<this-box>:9101/ask",
          "description": "ops agent on the mac mini"}
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

HUB = os.getenv("HERMES_HUB", "http://localhost:8484").rstrip("/")
SECRET = os.getenv("HERMES_SECRET", "")
HEADERS = {"X-Hermes-Secret": SECRET}

app = FastAPI(title="example remote agent")


class Ask(BaseModel):
    message: str
    # sender field is named "from" in the wire format; FastAPI ignores extras


class Ev(BaseModel):
    type: str
    ts: str = ""
    data: dict = {}


@app.post("/ask")
def ask(a: Ask) -> dict:
    """Hermes (voice) is asking this agent something mid-call.
    Put your real agent logic here."""
    return {"reply": f"ops agent here — I received: '{a.message}'. "
                     "All systems nominal on the mini."}


@app.post("/events")
def events(e: Ev) -> dict:
    """Receives the hub's event stream (agent_exchange, ring, call_ended…)."""
    print(f"[stream] {e.type}: {e.data}")
    return {"ok": True}


# ── Helpers your remote agent can call to DRIVE Hermes ────────────────

def make_hermes_call_user(nudge: str) -> None:
    """Decide the user needs a call -> Hermes rings them on Telegram."""
    httpx.post(f"{HUB}/webhook/ring", headers=HEADERS,
               json={"nudge": nudge, "source": "ops"}, timeout=15)


def publish(event_type: str, data: dict) -> None:
    httpx.post(f"{HUB}/webhook/event", headers=HEADERS,
               json={"type": event_type, "data": data, "source": "ops"}, timeout=10)


def subscribe(my_public_url: str) -> None:
    """Call once at startup to join the event stream."""
    httpx.post(f"{HUB}/webhook/subscribe", headers=HEADERS,
               json={"url": f"{my_public_url.rstrip('/')}/events"}, timeout=10)
