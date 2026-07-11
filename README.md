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

### Design principles

1. **Agents are processes, not prompts.** Each agent is an independent service with its own persona document (`net_agents/context/<agent>.md`), its own state, and its own brain. Kill one, the rest keep running; the hub degrades gracefully.
2. **Text in, text out.** The `/ask` contract is the entire interface. Any agent (or human, or curl) can talk to any other agent. Adding an agent = one file + one registry entry.
3. **The browser is real.** No headless scraping API pretending to be "browsing" — a stealth Firefox (Camoufox) with real OS-level input runs in Docker, and the dashboard streams its screen over noVNC. When Buddy looks something up, you can *watch it*.
4. **Memory models attention, not storage.** The bookkeeper weights items on a bell curve around *now* (working memory) with a separate long-term store that only decays on completion or expiry — mirroring what ADHD working memory can't do.
5. **Fallback chains everywhere.** Every brain call has a fallback (local Hermes runtime → cloud model → rule-based reply). A live voice call must never hang on a single point of failure.
6. **Local-first.** The mesh, the memory, the browser, the dashboard, and the STT (local Whisper) run on one machine on your LAN. Cloud is used only for LLM inference and the voice layer.

### Components

| Component | Port | Role |
|-----------|------|------|
| Hub (`agent_hub.py`) | 8484 | Agent registry, routing, dashboard/docs/memory API, webhook endpoints for the voice agent |
| Bookkeeper (`net_agents/bookkeeper.py`) | 9102 | The user's memory: capture, recall, defer, complete — Hermes runtime primary, cloud fallback |
| Browser (`net_agents/browser.py`) | 9103 | Web lookups on a real stealth browser; visible live via noVNC |
| Orchestrator (`net_agents/orchestrator.py`) | 9104 | Manager: decomposes "build me X", routes to planner/builder, tracks a task ledger |
| Telegram bridge (`bot.py`) | — | Voice notes ↔ agent loop (local Whisper STT, Edge TTS) |
| Voice agent (ElevenLabs) | cloud | Live conversational body-double; reaches the mesh via webhook tools |
| Stealth browser | 8080 / 5900 | Camoufox + PyAutoGUI in Docker; JSON API + live noVNC view |
| Dashboard (`Buddy-frontend/`) | 5500 | Live agent graph, productivity analytics, per-agent docs & memory |

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

# the whole stack: hub + tunnel + bot + agents, self-healing URLs
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
