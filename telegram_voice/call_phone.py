"""LIVE call via ElevenLabs Agents + Twilio — your phone actually rings
and you talk to Hermes in real time (streaming STT/TTS, barge-in included).

Usage:
  .venv\\Scripts\\python.exe call_phone.py                       (default check-in)
  .venv\\Scripts\\python.exe call_phone.py "You said 3pm was report time."

The optional argument becomes the agent's opening line AND is added to its
context for this call, so Hermes can nudge about something specific.
(Requires overrides enabled: Agent -> Security -> enable First message +
System prompt overrides.)

Needs in .env: ELEVENLABS_API_KEY, EL_AGENT_ID, EL_PHONE_NUMBER_ID, MY_PHONE_NUMBER
"""
from __future__ import annotations

import os
import sys

import config  # first: applies the Windows SSL cert-store fix

import httpx

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
AGENT_ID = os.getenv("EL_AGENT_ID", "")
PHONE_NUMBER_ID = os.getenv("EL_PHONE_NUMBER_ID", "")
TO_NUMBER = os.getenv("MY_PHONE_NUMBER", "")

DEFAULT_OPENER = (
    "Hey, it's Hermes checking in. What are you working on right now?"
)


def call_phone(opener: str) -> None:
    missing = [k for k, v in {
        "ELEVENLABS_API_KEY": API_KEY, "EL_AGENT_ID": AGENT_ID,
        "EL_PHONE_NUMBER_ID": PHONE_NUMBER_ID, "MY_PHONE_NUMBER": TO_NUMBER,
    }.items() if not v]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)} (see README, Tier C)")

    body = {
        "agent_id": AGENT_ID,
        "agent_phone_number_id": PHONE_NUMBER_ID,
        "to_number": TO_NUMBER,
        "conversation_initiation_client_data": {
            "conversation_config_override": {
                "agent": {"first_message": opener}
            },
            "dynamic_variables": {"nudge_context": opener},
        },
    }
    r = httpx.post(
        "https://api.elevenlabs.io/v1/convai/twilio/outbound-call",
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    if r.status_code >= 400:
        raise SystemExit(f"ElevenLabs error {r.status_code}: {r.text}")
    data = r.json()
    print(f"ringing {TO_NUMBER} — conversation_id={data.get('conversation_id')} "
          f"callSid={data.get('callSid')}")


if __name__ == "__main__":
    call_phone(" ".join(sys.argv[1:]).strip() or DEFAULT_OPENER)
