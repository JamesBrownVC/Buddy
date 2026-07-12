# Buddy — architecture & rules of engagement

This document is the authoritative map of this repository. **Read it fully
before changing anything.** It is written so that any model — however small —
can work here without destroying the system. When in doubt: change nothing,
ask, or make the smallest possible edit.

## Golden rules (read twice)

1. **NEVER commit secrets.** `.env` files, API keys, tokens, brain keys.
   Before every commit run the secret gate:
   `git diff --cached | grep -E "sk-proj-|nvapi-|[0-9]{8,}:AA[A-Za-z0-9_-]{30}"` → must be empty.
2. **NEVER touch `telegram_voice/.env`** except to ADD a new key. Never delete,
   never rewrite wholesale, never print its contents into logs or replies.
3. **NEVER delete or rewrite `telegram_voice/state/`** (runtime data: task log,
   memories, transcripts, logs). It is gitignored. Losing it loses the user's memory.
4. **NEVER change the port map** (below). Everything cross-references it.
5. **NEVER change the `/ask` contract** (`POST {"message": ...} → {"reply": ...}`)
   or the `/agents/ask` contract (`{"agent","message","from"}`). Every agent,
   tool and the hub depend on it.
6. **NEVER add silent fallbacks.** Doctrine: an agent that cannot do its job
   says so and asks for help (repair agent, router). A degraded mode that
   pretends to work is worse than an honest failure.
7. **NEVER "clean up" things you don't understand** — no renaming files,
   reformatting whole modules, or deleting "unused-looking" code. Personas in
   `net_agents/context/*.md` are load-bearing prompts, not docs to rewrite.
8. **Restart, don't reimplement.** If something is down, use the lifecycle
   engine (`net_agents/lifecycle.py`, `wake_agent`) — do not write a new
   launcher or a new health system.
9. **One small change at a time**, verified before the next.

## Nomenclature (use these words exactly)

| Term | Means |
|---|---|
| **agent** | A network member reachable at `POST :port/ask`. Almost all are Hermes agents. |
| **brain** | An agent's Hermes runtime (its own Hermes profile + OpenAI-compatible API server). One brain per agent. |
| **forwarder** | The thin FastAPI app (`net_agents/<name>.py`) that forwards `/ask` to the brain. It contains NO logic. Keep it 3 lines. |
| **profile** | The Hermes config dir `~/.hermes/profiles/<name>brain/` (config.yaml + SOUL.md persona). |
| **hub** | `agent_hub.py` (:8484). Message bus, ElevenLabs tools, task log, dashboard API, auth. |
| **router** | `net_agents/router.py` (:9108). Lightweight dispatcher, deliberately NOT a Hermes agent. |
| **MCP toolset** | A stdio server in `net_mcp/*.py` attached to a profile. Keep per-agent toolsets MINIMAL. |
| **persona / context doc** | `net_agents/context/<name>.md`. The agent's system prompt. |
| **task log** | `state/task_log.jsonl`. Every `/agents/ask` with macro/micro attribution. |
| **memory** | Per-agent `state/memory/<agent>.jsonl` via `memory_store.py` (relevance × recency bell-curve × importance + long-term). |
| **lifecycle** | `net_agents/lifecycle.py`. The ONLY sanctioned way to health-check/revive agents. |

## Port map (authoritative — do not reassign)

| Port | What |
|---|---|
| 8484 | agent hub |
| 8643–8649 | brains: buddy(bookkeeper), browser, orch, builder, repair, toolsmith, audit |
| 8650 | terra proxy (gpt-5.6-terra sanitizer for all cloud brains) |
| 8651 | personalbrain (LOCAL Ollama model — personal data agent) |
| 9102–9109 | agent services: bookkeeper, browser, orchestrator, builder, repair, toolsmith, router, audit |
| 9112 | personal agent service |
| 11434 | Ollama (local models) |
| 8080 / 5900 | stealth browser container `browser` (API / noVNC) — the browser agent's |
| 8081 / 5901 | stealth browser container `browser-private` — the personal agent's ONLY |
| 9110+ | builder-generated agents (ports recorded in `agents.json`) |

## Directory map

```
Buddy/
├── ARCHITECTURE.md            ← this file (keep in sync with reality)
├── SECURITY.md                ← threat model; do not weaken what it promises
├── tests/                     ← security tests; MUST pass before any commit
├── Buddy-frontend/            ← dashboard page (served locally)
└── telegram_voice/
    ├── .env                   ← SECRETS. Read-only. Never commit, never print.
    ├── agents.json            ← agent registry + capability specs the router reads
    ├── agent_hub.py           ← hub (see above)
    ├── terra_proxy.py         ← request sanitizer for gpt-5.6; don't touch
    ├── start_all_mac.py       ← the ONE launcher; keep its lists in sync with the port map
    ├── setup_hermes_brains.py ← writes brain profiles; re-runnable; edit HERE, not profiles, for cloud brains
    ├── setup_elevenlabs.py    ← pushes voice tools to ElevenLabs; requires explicit URL arg
    ├── security_utils.py      ← signing/secrets helpers; changes need test updates
    ├── net_agents/
    │   ├── hermes_service.py  ← make_agent_app(); the /ask + /health contract lives here
    │   ├── lifecycle.py       ← health/wake engine
    │   ├── memory_store.py    ← bell-curve memory engine
    │   ├── router.py          ← dispatcher
    │   ├── <name>.py          ← forwarders (3 lines each — keep them dumb)
    │   └── context/<name>.md  ← personas (edit carefully, never bulk-rewrite)
    ├── net_mcp/               ← MCP toolsets (one file per concern, minimal tools)
    └── state/                 ← RUNTIME DATA + logs. Never commit. Never delete.
```

## How things talk

```
user (Telegram/voice/dashboard)
   → hub :8484 /agents/ask {"agent","message","from"}
      → forwarder :91xx /ask   → brain :86xx (Hermes agent turn, uses MCP tools)
          brain may call peers via agent_bridge → hub /agents/ask (from=<agent>)
          or ask the router :9108 to pick a target
   ← reply flows back up; hub logs macro/micro to state/task_log.jsonl
```
If the target's service or brain is dead, the hub **auto-wakes** it and retries
(mailbox wake). The audit & repair agents can also `wake_agent(...)` themselves.

## The ONLY correct way to add a new agent

1. Persona in `net_agents/context/<name>.md` (include the standard
   "Working in the network" section — copy from an existing persona).
2. Profile: add to `setup_hermes_brains.py` BRAINS (cloud brains) and run it —
   or for special providers (local models) copy `personalbrain`'s config.yaml pattern.
3. Forwarder `net_agents/<name>.py`: exactly
   `app = make_agent_app("<name>", brain_port=<86xx>, brain_key="<name>brain-local")`.
4. Register in `agents.json` with an honest, specific `description`
   (the router routes on it — a vague description = misrouting).
5. Add to `start_all_mac.py` (brain + service lists) and
   `lifecycle.py` FIRST_CLASS. Generated agents instead set
   `"generated": true` + ports in `agents.json` (picked up automatically).
6. Health-check both ports, send one real `/ask`, THEN commit.

## Restarting things (in order of preference)

1. `wake_agent(name)` / hub `POST /agents/wake` — fixes 95% of outages.
2. `hermes -p <profile> gateway run --replace` — brain only; `--replace` is
   mandatory (clears stale locks and desktop-app hijacks).
3. `.venv/bin/python start_all_mac.py` — full stack, only if hub itself is dead.
4. NEVER `kill -9` a gateway and walk away; always start the replacement.

## Known failure modes → correct fix

| Symptom | Cause | Fix |
|---|---|---|
| agent replies "Hermes runtime is unavailable" | brain down | `wake_agent(name)` |
| brain log: "Another gateway instance is already running" | stale lock / desktop-app hijack | restart with `--replace` |
| hub 401 from localhost | hub running stale code | restart hub |
| tunnel URL dead | quick tunnels rotate on cloudflared restart | re-run launcher step / `setup_elevenlabs.py <new url>` |
| browser "falls back to duckduckgo" | browser brain down or container down | wake browser; `docker start browser` |
| voice page shows no button | widget missing `agent-id` or EL misconfig | see `/answer` in agent_hub.py; don't rewrite the page |

## Secrets & privacy invariants

- Cloud brains (gpt-5.6) must NEVER be given raw personal data dumps (emails,
  chats). Personal-data work belongs to the **personal** agent (local model,
  own browser session, nothing leaves the machine).
- The hub requires `X-Hermes-Secret` for every tunneled request; localhost is
  exempt. Do not add paths to `PUBLIC_PATHS` beyond `/answer`, `/health`, `/post_call`.
- Signed links (`sign_answer_link`) expire by design. Do not remove expiry.
- Never widen CORS beyond the local dashboard origins.

## Before you claim "done"

1. `python -m pytest tests/ -q` → all pass.
2. Health-sweep the ports you touched.
3. One real end-to-end ask through the hub.
4. Secret gate, then commit with a message saying WHAT and WHY.
