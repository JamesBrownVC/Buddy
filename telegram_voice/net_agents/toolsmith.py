"""Toolsmith — a Hermes autonomous agent that forges deterministic tools.
Its Hermes runtime (toolsmithbrain :8648) creates HTTP/MCP tools and attaches
them to the right specialist agent (build_tool MCP); this is a thin forwarder."""
from net_agents.hermes_service import make_agent_app
app = make_agent_app("toolsmith", brain_port=8648, brain_key="toolsmithbrain-local")
