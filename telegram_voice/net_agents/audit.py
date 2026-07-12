"""Audit — a Hermes autonomous agent that reviews how the network performs.
It reads the task log (each action vs its ask, latency, failures) via audit_tools
and makes surgical improvements (ask toolsmith for a tool, builder for an agent).
Thin forwarder to its Hermes runtime (auditbrain :8649)."""
from net_agents.hermes_service import make_agent_app
app = make_agent_app("audit", brain_port=8649, brain_key="auditbrain-local")
