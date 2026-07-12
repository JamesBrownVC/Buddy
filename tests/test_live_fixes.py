"""Hub-endpoint tests for the live-issue fixes: the inference gate (try_answer),
the unified bookkeeper memory read, and the voice remember/recall namespace."""
from __future__ import annotations

import os
import sys
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


class InferenceGateTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(agent_hub.app)
        self.auth = {"X-Hermes-Secret": os.environ["HUB_SECRET"]}

    def test_confident_inference_answers_without_asking_user(self):
        with patch("agent_hub._infer_answer",
                   return_value={"confidence": 0.9, "answer": "Paris"}), \
                patch("net_agents.memory_store.recall", return_value=[]):
            r = self.client.post("/agents/try_answer",
                                 headers=self.auth,
                                 json={"question": "what city is INSEAD's Europe campus in?"})
        body = r.json()
        self.assertTrue(body["answered"])
        self.assertEqual(body["answer"], "Paris")

    def test_low_confidence_defers_to_user(self):
        with patch("agent_hub._infer_answer",
                   return_value={"confidence": 0.3, "answer": ""}), \
                patch("net_agents.memory_store.recall", return_value=[]):
            r = self.client.post("/agents/try_answer",
                                 headers=self.auth,
                                 json={"question": "what's your mother's maiden name?"})
        self.assertFalse(r.json()["answered"])

    def test_threshold_is_honoured(self):
        with patch("agent_hub._infer_answer",
                   return_value={"confidence": 0.72, "answer": "maybe"}), \
                patch("net_agents.memory_store.recall", return_value=[]):
            # a 0.8 threshold rejects a 0.72-confidence answer
            r = self.client.post("/agents/try_answer", headers=self.auth,
                                 json={"question": "q", "threshold": 0.8})
        self.assertFalse(r.json()["answered"])


class BookkeeperDashboardTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(agent_hub.app, client=("127.0.0.1", 50000))

    def test_dashboard_shows_live_bookkeeper_memory(self):
        items = [
            {"ts": 1_700_000_000, "text": "James is at INSEAD in France", "longterm": True},
            {"ts": 1_700_000_100, "text": "Reply to Sam about Q3 deck", "longterm": False},
        ]
        with patch("net_agents.memory_store._load", return_value=items):
            r = self.client.get("/api/agent-memory?name=bookkeeper")
        body = r.json()
        self.assertTrue(body["found"])
        texts = [i["text"] for i in body["working"]] + [i["text"] for i in body["longterm"]]
        self.assertIn("James is at INSEAD in France", texts)   # the real user fact shows
        self.assertEqual(len(body["longterm"]), 1)             # split by longterm flag


if __name__ == "__main__":
    unittest.main()
