"""Orchestrator — a Hermes autonomous agent (manager/router)."""
import os
from net_agents.hermes_service import make_agent_app
_key = os.getenv("ORCH_BRAIN_KEY") or open(
    os.path.join(os.path.dirname(__file__), "..", "state", "orchbrain.key")).read().strip()
app = make_agent_app("orchestrator", brain_port=8645, brain_key=_key)
