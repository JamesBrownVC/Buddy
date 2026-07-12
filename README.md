# Buddy

**An external executive function for people with ADHD — a voice-first network of agents that remembers, initiates, and follows through, so you don't have to.**

🏆 Winner, Hermes Buildathon 2026.

---

## The problem

ADHD is not a knowledge problem. People with ADHD usually know exactly what they should do — the deficit is in the *doing*: task initiation, working memory, time-perception, and follow-through. The research is consistent:

- **Working memory** is impaired in the large majority of ADHD cases — the mental scratchpad drops things within seconds.
- **Prospective memory** ("remembering to remember") fails precisely when it matters: at the moment action is needed.
- **Time blindness** makes durations unreliable — "I'll leave in 5 minutes" quietly becomes 45.
- **Task initiation** carries a neurologically elevated activation barrier: starting is the hardest part, continuing is fine.
- **Rejection sensitivity** means every nagging reminder app that shames a missed task makes the problem worse, not better.

Every mainstream productivity tool assumes the exact abilities ADHD impairs: you must remember to open the app, hold the plan in your head, estimate time correctly, and tolerate guilt when you slip. That's why they get abandoned.

**Buddy inverts the contract.** You never have to remember Buddy exists. It lives where you already are — a phone call, a Telegram voice note — captures whatever you throw at it in half-sentences, holds the plan *for* you, shrinks every task to one small physical next step, nudges at the moment action is needed, and never, ever shames you. A dropped task is data, not a failure.

---

## Architecture

Buddy is a mesh of small, single-purpose agents behind one hub, running entirely on local hardware (a Mac mini). Every agent speaks one tiny contract — `POST /ask {"message": ...}` → `{"reply": ...}` — so agents compose: the voice agent can delegate to any of them mid-call, and they can delegate to each other.

```
                        ┌──────────────────────────────────────────────┐
   you ── voice call ──►│  ElevenLabs conversational agent             │
   you ── Telegram ────►│  (persona: evidence-based ADHD body-double)  │
                        └───────────────┬──────────────────────────────┘
                                        │ webhook tools (ask_agent, remember, …)
                              cloudflared tunnel
                                        │
                        ┌───────────────▼───────────────┐
                        │        Hub  (FastAPI :8484)    │
                        │  agent registry · routing ·    │
                        │  dashboard / docs / memory API │
                        └──┬──────────┬──────────┬───────┘
                           │          │          │
                ┌──────────▼───┐ ┌────▼─────┐ ┌──▼───────────┐
                │  Bookkeeper  │ │ Browser  │ │ Orchestrator │
                │  :9102       │ │ :9103    │ │ :9104        │
                │  the user's  │ │ drives a │ │ routes multi-│
                │  memory      │ │ REAL     │ │ step "build  │
                │  (bell-curve │ │ stealth  │ │ me X" work   │
                │  attention)  │ │ browser  │ │ to planner / │
                └──────┬───────┘ └────┬─────┘ │ builder      │
                       │              │       └──────────────┘
                 Hermes runtime   Camoufox in Docker
                 (:8643, local)   API :8080 · noVNC :5900 (watch it live)

                        ┌────────────────────────────────┐
                        │  Dashboard (static, :5500)     │
                        │  live agent graph · weekly     │
                        │  productivity analytics ·      │
                        │  click a node → its docs +     │
                        │  live memory · live browser tab│
                        └────────────────────────────────┘
```

### Every agent is a Hermes autonomous agent

Each specialist is a **Hermes agent** — its own [Hermes](https://hermes-agent.nousresearch.com) instance (profile) running gpt-5.6-terra, with a persona (`SOUL.md`), its own tools, and its own autonomous agent-loop. The `net_agents/<name>.py` service is a *thin forwarder* (`hermes_service.make_agent_app`) that hands the text to that Hermes runtime and returns whatever the agent autonomously decides — **no reasoning lives in the Python.**

Agents collaborate through **MCP tools**, not hard-coded orchestration:
- `net_mcp/agent_bridge.py` gives every agent `list_agents` + `ask_agent(agent, text)`, so a Hermes agent *decides for itself* to message a peer over text (verified: the bookkeeper agent autonomously calls the browser agent mid-task).
- `net_mcp/browser_tools.py` gives the browser agent `web_search` / `open_url` that drive the visible stealth container.
- `net_mcp/memory_tools.py` gives the bookkeeper agent `remember` / `recall` / `complete` over the shared memory store.

So the mesh is genuinely autonomous agents talking to autonomous agents — each async, each deciding how to handle a request and when to delegate.

### Tools vs agents, and minimal footprint

Not every capability needs a reasoning agent. A weather lookup is a *deterministic tool* (one API call), not an agent. The **Toolsmith** (a Hermes agent, itself built by the Builder) forges deterministic MCP tools — `net_mcp/toolsmith_tools.build_tool` generates a small HTTP-GET MCP server (`net_mcp/generated/<tool>.py`) and attaches it to **one** specialist agent's Hermes profile.

The guiding rule is **minimal tools per agent**: each agent carries only `agent_bridge` (for delegation) plus a small, minimal built-in toolset (`platform_toolsets: {api_server: [todo]}`, so agents don't wander into `execute_code`/terminal) and at most its own role tool. When an agent needs a capability it doesn't own, it **asks the specialist that does** — e.g. the bookkeeper doesn't carry a weather tool; asked about the weather it delegates to the browser agent, which owns `get_weather`. Specialized agents collaborating beats one agent with a hundred tools.

### Not everything is a Hermes agent

The network has three kinds of node, unified by the one `/ask` text contract so they're interchangeable to callers:

- **Hermes autonomous agents** — the specialists (bookkeeper, browser, orchestrator) and the meta-agents (builder, repair, toolsmith). They reason.
- **Deterministic tools** — MCP connectors the Toolsmith forges, attached to one agent. They don't reason.
- **Lightweight utilities** — e.g. the **Router** (`net_agents/router.py`, :9108): a request an agent can't handle goes to the router, which makes *one* fast model call to pick the best agent and forwards it. Routing is a trivial classification, so it is deliberately **not** a Hermes agent — a full agent-loop there would just add latency in the critical path. Agents lean on the router when unsure who should handle something, instead of each reasoning over the whole (growing) roster. When the router can't place a request it escalates to the **orchestrator**, which force-routes or builds a new agent/tool.

### Memory and self-audit

- **Per-agent memory** (`net_mcp/memory_layer.py`): every agent has its own private memory (`state/memory/<agent>.jsonl`). Recall ranks by **relevance** (embedding similarity — a small RAG) × **recency** (a Gaussian "bell curve" around now, so recent things get the most attention) × **importance**, plus a non-decaying **long-term** layer. The bookkeeper additionally curates a durable profile of the user (it can ask the browser to mine the user's own email/calendar and keeps only the salient facts).
- **Self-audit** (`net_agents/audit.py`, :9109): the hub logs every action to `state/task_log.jsonl` (the ask, the reply, latency, success, and the macro→micro delegation tree). The **Audit** agent (built by the Builder) reads that log, judges each action against its ask, and requests surgical improvements — a tool from the Toolsmith or a new agent from the Builder — conservatively, on repeated evidence.

### Design principles

1. **Agents are Hermes runtimes, not prompts.** Each agent is an independent Hermes process with its own persona, tools, and MCP peer-messaging. Kill one, the rest keep running; the hub degrades gracefully.
2. **Text in, text out.** The `/ask` contract is the entire interface. Any agent (or human, or curl) can talk to any other agent. Adding an agent = one Hermes profile + a two-line forwarder + one registry entry — which is exactly what the Builder automates.
3. **The browser is real.** No headless scraping API pretending to be "browsing" — a stealth Firefox (Camoufox) with real OS-level input runs in Docker, and the dashboard streams its screen over noVNC. When Buddy looks something up, you can *watch it*.
4. **Memory models attention, not storage.** The bookkeeper weights items on a bell curve around *now* (working memory) with a separate long-term store that only decays on completion or expiry — mirroring what ADHD working memory can't do.
5. **Pure Hermes, no fallbacks.** Every agent runs on its Hermes runtime — no direct-model bypass, no invisible search fallback. If a runtime is down the agent says so (and the Repair agent fixes it) rather than silently degrading.
6. **Local-first.** The mesh, the memory, the browser, the dashboard, and the STT (local Whisper) run on one machine on your LAN. Cloud is used only for LLM inference and the voice layer.

### Components

| Component | Port | Role |
|-----------|------|------|
| Hub (`agent_hub.py`) | 8484 | Agent registry, routing, dashboard/docs/memory/roster API, webhook endpoints for the voice agent |
| Bookkeeper (`net_agents/bookkeeper.py`) | 9102 | The user's memory: capture, recall, defer, complete |
| Browser (`net_agents/browser.py`) | 9103 | Web lookups on the **visible** stealth browser (never silently degrades) |
| Orchestrator (`net_agents/orchestrator.py`) | 9104 | Manager: decomposes "build me X", routes across the mesh, task ledger |
| **Builder** (`net_agents/builder.py`) | 9105 | A Hermes agent that **builds new agents on demand** (via its `build_agent` MCP tool) — the network is auto-expandable |
| **Repair** (`net_agents/repair.py`) | 9106 | A Hermes agent that **self-heals** (MCP tools: scan health, restart agents, recreate the stealth browser, restart brains) using the failure log |
| Telegram bridge (`bot.py`) | — | Voice notes ↔ agent loop (local Whisper STT, Edge TTS) |
| Voice agent (ElevenLabs) | cloud | Live conversational body-double; reaches the mesh via webhook tools |
| Terra proxy (`terra_proxy.py`) | 8650 | Sanitises Hermes' request body so every brain runs **gpt-5.6-terra** |
| Hermes brains | 8643-8645+ | One local Hermes instance per agent (gpt-5.6-terra via the proxy) |
| Stealth browser | 8080 / 5900 | Camoufox + PyAutoGUI in Docker; JSON API + live noVNC view |
| Dashboard (`Buddy-frontend/`) | 5500 | Live agent graph (generated agents appear automatically), productivity analytics, per-agent docs & memory |

### Self-extending & self-healing

- **Builder** turns a one-line spec into a complete new agent: it creates a Hermes
  profile (gpt-5.6-terra via the proxy) with a generated persona, writes a
  `net_agents/<name>.py` service, registers it, and launches it. The new agent is
  instantly callable by every other agent (`ask_agent('<name>')`) and appears as a
  node in the dashboard graph.
- **Repair** consumes a structured failure log (`state/failures.jsonl`) that every
  agent writes to, retrieves the most relevant recent failures with a tiny
  dependency-free local RAG, diagnoses with its own gpt-5.6 brain, and executes
  concrete fixes (restart a dead agent, recreate the browser container, restart a
  Hermes brain or the proxy). Ask it `scan`, then `repair`.
- **The browser always uses the visible stealth browser.** Any degrade to the
  invisible text fallback is logged as a repairable failure — so Repair fixes the
  browser rather than the system silently limping on DuckDuckGo.

---

## Quick start (macOS)

Prerequisites: Python 3.11 · Docker (Colima) · cloudflared · ffmpeg · a Telegram bot token · OpenAI + ElevenLabs API keys.

```bash
cd telegram_voice
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env          # fill in your keys — .env is gitignored

# stealth browser
colima start --cpu 2 --memory 4
docker run -d --name browser --restart unless-stopped \
  -p 8080:8080 -p 5900:5900 psyb0t/stealthy-auto-browse

# create the per-agent Hermes brains (needs Hermes installed + OPENAI_API_KEY set)
.venv/bin/python setup_hermes_brains.py

# the whole stack: terra proxy + Hermes brains + hub + tunnel + bot + agents
.venv/bin/python start_all_mac.py

# provision the ElevenLabs agent + its webhook tools
.venv/bin/python setup_elevenlabs.py "<the tunnel URL printed above>"
```

Dashboard: `http://<lan-ip>:5500` · Live browser: `http://<lan-ip>:5900` · Telegram: `/start`, then `/call`.

---

## Security

- Secrets live only in `.env` (gitignored); the repo ships `.env.example`.
- Runtime state, memory JSON, and browser sessions are gitignored.
- The hub exposes only read-only doc/memory endpoints without auth; agent routing endpoints can be gated with a shared secret (`HUB_SECRET`).

## License & contributing

Open source — issues and PRs welcome. The most valuable contributions right now: new agents (calendar, email triage), more messaging surfaces, and evidence-based refinements to the ADHD interaction patterns in `research/`.
