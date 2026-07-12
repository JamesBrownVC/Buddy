"""Bookkeeper — a Hermes autonomous agent (memory). See hermes_service."""
from net_agents.hermes_service import make_agent_app
app = make_agent_app("bookkeeper", brain_port=8643, brain_key="buddybrain-local")
