"""Builder — a Hermes autonomous agent that builds new agents.
Its Hermes runtime (builderbrain :8646) designs and creates agents via the
builder_tools MCP tool; this service just forwards /ask to it."""
from net_agents.hermes_service import make_agent_app
app = make_agent_app("builder", brain_port=8646, brain_key="builderbrain-local")
