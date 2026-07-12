"""personal agent — thin forwarder to its FULLY LOCAL Hermes brain.

The brain (profile `personalbrain`, :8651) runs nemotron-3-nano on the local
Ollama server (:11434), so private data — emails, chats, documents — never
leaves this machine. It drives its own stealth-browser session (container
`browser-private`, API :8081, noVNC :5901), separate from the public
browser agent's.
"""
from net_agents.hermes_service import make_agent_app

app = make_agent_app("personal", brain_port=8651, brain_key="personalbrain-local")
