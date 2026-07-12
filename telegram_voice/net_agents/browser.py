"""Browser — a Hermes autonomous agent driving the visible stealth browser."""
from net_agents.hermes_service import make_agent_app
app = make_agent_app("browser", brain_port=8644, brain_key="browserbrain-local")
