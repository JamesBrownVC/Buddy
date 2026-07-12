from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TV = ROOT / "telegram_voice"
sys.path.insert(0, str(TV))
os.environ.setdefault("HUB_SECRET", "test-hub-secret-that-is-long-enough-for-tests")
os.environ.setdefault("ELEVENLABS_API_KEY", "test-elevenlabs-key")
os.environ.setdefault("EL_AGENT_ID", "agent_test")
os.environ.setdefault("ELEVENLABS_WEBHOOK_SECRET", "test-webhook-secret")

from fastapi.testclient import TestClient  # noqa: E402

import agent_hub  # noqa: E402
from net_agents import hermes_service  # noqa: E402
from security_utils import sign_answer_link, verify_elevenlabs_signature  # noqa: E402


class _SignedUrlResponse:
    status_code = 200

    @staticmethod
    def raise_for_status() -> None:
        return None

    @staticmethod
    def json() -> dict:
        return {"signed_url": "wss://api.elevenlabs.io/test?conversation_signature=safe"}


class HubSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(agent_hub.app)
        self.auth = {"X-Hermes-Secret": os.environ["HUB_SECRET"]}

    def test_private_memory_requires_authentication(self) -> None:
        response = self.client.get("/api/agent-memory?name=bookkeeper")
        self.assertEqual(response.status_code, 401)

    def test_direct_localhost_keeps_dashboard_and_memory_available(self) -> None:
        local = TestClient(agent_hub.app, client=("127.0.0.1", 50000))
        self.assertEqual(local.get("/api/dashboard-state").status_code, 200)
        self.assertEqual(
            local.get("/api/agent-memory?name=bookkeeper").status_code, 200
        )

    def test_tunneled_request_cannot_use_localhost_bypass(self) -> None:
        local = TestClient(agent_hub.app, client=("127.0.0.1", 50000))
        response = local.get(
            "/api/agent-memory?name=bookkeeper",
            headers={"CF-Connecting-IP": "203.0.113.10", "CF-Ray": "test"},
        )
        self.assertEqual(response.status_code, 401)

    def test_wrong_bearer_token_is_rejected(self) -> None:
        response = self.client.get(
            "/api/dashboard-state", headers={"Authorization": "Bearer wrong"}
        )
        self.assertEqual(response.status_code, 401)

    def test_untrusted_cors_origin_is_not_allowed(self) -> None:
        response = self.client.options(
            "/api/dashboard-state",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
                **self.auth,
            },
        )
        self.assertNotEqual(response.headers.get("access-control-allow-origin"), "https://evil.example")

    def test_answer_link_requires_valid_expiring_signature(self) -> None:
        self.assertEqual(self.client.get("/answer").status_code, 403)
        nudge = "hello'><script>alert(1)</script>"
        expires, signature = sign_answer_link(nudge)
        no_follow = TestClient(agent_hub.app, follow_redirects=False)
        response = no_follow.get(
            "/answer", params={"nudge": nudge, "expires": expires, "sig": signature}
        )
        self.assertEqual(response.status_code, 302)
        location = response.headers["location"]
        self.assertTrue(location.startswith("https://elevenlabs.io/app/talk-to?"))
        self.assertIn("var_nudge_context=", location)
        self.assertNotIn("<script>", location)

    def test_dashboard_voice_session_is_private(self) -> None:
        self.assertEqual(self.client.post("/api/voice-session").status_code, 401)
        with patch.object(agent_hub.httpx, "get", return_value=_SignedUrlResponse()):
            response = self.client.post("/api/voice-session", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["signed_url"].startswith("wss://"))

    def test_post_call_rejects_unsigned_and_traversal_ids(self) -> None:
        payload = {
            "type": "post_call_transcription",
            "data": {"conversation_id": "../../outside", "analysis": {}},
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.assertEqual(self.client.post("/post_call", content=body).status_code, 401)
        timestamp = int(time.time())
        digest = hmac.new(
            os.environ["ELEVENLABS_WEBHOOK_SECRET"].encode(),
            str(timestamp).encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        response = self.client.post(
            "/post_call",
            content=body,
            headers={"ElevenLabs-Signature": f"t={timestamp},v0={digest}"},
        )
        self.assertEqual(response.status_code, 400)

    def test_valid_post_call_is_idempotent_and_does_not_store_raw_by_default(self) -> None:
        payload = {
            "type": "post_call_transcription",
            "data": {
                "conversation_id": "conv_safe-123",
                "analysis": {"transcript_summary": "A safe local summary"},
            },
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        timestamp = int(time.time())
        digest = hmac.new(
            os.environ["ELEVENLABS_WEBHOOK_SECRET"].encode(),
            str(timestamp).encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        headers = {"ElevenLabs-Signature": f"t={timestamp},v0={digest}"}

        async def no_broadcast(*_args, **_kwargs) -> None:
            return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(agent_hub, "TRANSCRIPTS", root), \
                    patch.object(agent_hub, "MEMORY_FILE", root / "memory.md"), \
                    patch.object(agent_hub, "broadcast", no_broadcast), \
                    patch.dict(os.environ, {"STORE_CALL_TRANSCRIPTS": "0"}):
                first = self.client.post("/post_call", content=body, headers=headers)
                second = self.client.post("/post_call", content=body, headers=headers)
            self.assertEqual(first.status_code, 200)
            self.assertFalse(first.json()["duplicate"])
            self.assertTrue(second.json()["duplicate"])
            self.assertFalse((root / "conv_safe-123.json").exists())
            self.assertEqual((root / "memory.md").read_text().count("A safe local summary"), 1)

    def test_remote_subscribers_are_disabled_without_allowlist(self) -> None:
        response = self.client.post(
            "/webhook/subscribe",
            headers=self.auth,
            json={"url": "http://127.0.0.1:8080/private"},
        )
        self.assertEqual(response.status_code, 403)


class HelperSecurityTests(unittest.TestCase):
    def test_stale_elevenlabs_signature_is_rejected(self) -> None:
        body = b"{}"
        old = int(time.time()) - 600
        digest = hmac.new(
            b"secret", str(old).encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        self.assertFalse(
            verify_elevenlabs_signature(body, f"t={old},v0={digest}", "secret")
        )

    def test_agent_health_returns_503_when_brain_is_down(self) -> None:
        app = hermes_service.make_agent_app("test", 65530, "test-key")
        with patch.object(hermes_service.httpx, "get", side_effect=OSError("down")):
            response = TestClient(app).get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])


if __name__ == "__main__":
    unittest.main()
