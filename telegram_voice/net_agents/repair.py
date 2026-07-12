"""Repair — a Hermes autonomous agent that keeps the network healthy.
Its Hermes runtime (repairbrain :8647) inspects failures/health and fixes them
via the repair_tools MCP tools; this service just forwards /ask to it."""
from net_agents.hermes_service import make_agent_app
app = make_agent_app("repair", brain_port=8647, brain_key="repairbrain-local")
