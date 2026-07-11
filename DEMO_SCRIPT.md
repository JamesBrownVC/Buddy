# Buddy — Live On-Stage Demo Script

**Talking to the ElevenLabs voice bot (Hermes).** Everything runs locally on the Mac mini; all services are already up.

### Stage setup (before you start)
- **Left of screen:** the dashboard — `http://127.0.0.1:5500/index.html`. Watch the big **Browser card** (top-left), the dark **Focus card** (hero headline + steps), the **Your crew** list, the **"Not now, but safe"** list, and the **status pill** (top-right, "N agents ready").
- **Right of screen:** the real browser — noVNC `http://127.0.0.1:5900/vnc.html?autoconnect=true&resize=scale`. This is the actual stealth Camoufox. When Buddy browses, pages load here for real. This is your "it's not faked" proof.
- Tap the orange **Talk it out with Buddy** button to open the call. Let the bot speak first — it opens with *"Hey, it's Hermes checking in. What are you on right now?"* Wait for that, then go.

> **Read-me on the two slow beats:** the **browser lookup** and the **orchestrator build** each drive real LLM tool-loops (10–25s). That latency is the demo — it's a live agent doing real work. Each has a *talk-track* line below to say while it thinks. Say it, don't fill silence with "um".

---

## 1) The 90-second happy path — exact lines, in order

**BOT OPENS (you don't speak):** *"Hey, it's Hermes checking in. What are you on right now?"*

---

**① You say:**
> "Hey Buddy — quick one first. Who's on your team right now?"

- **Triggers:** `list_agents`
- **Audience sees:** Buddy names the mesh out loud — Browser, Bookkeeper, Orchestrator, Planner, Coach. It matches the **Your crew** card on the left and the **"N agents ready"** status pill. Instant (~2s). Establishes that this is a *network*, not one bot.

---

**② You say:**
> "I'm prepping this demo and my brain keeps stalling. Can you look up what a body double means for ADHD, and give me the one-line version?"

- **Triggers:** `ask_agent('browser', …)` → real Camoufox navigation
- **Talk-track while it works (say this):** "Watch the screen on the right — that's Buddy actually opening a browser, not a canned answer."
- **Audience sees:** on the **noVNC screen (right)** a real page loads. On the left, the **Browser card** retitles to your question, its status flips to **● live**, then fills with the answer snippet. Buddy relays one clean sentence. (~15–25s.)

---

**③ You say:**
> "Perfect. Put on my list that the demo is at four PM today and I still need to rehearse it twice."

- **Triggers:** `ask_agent('bookkeeper', …)` (a *dated commitment* — "four PM today" — routes to the bookkeeper, which is what moves the dashboard)
- **Audience sees:** a new row appears in the **"Not now, but safe"** list on the right of the dashboard — "rehearse the demo… · today". Buddy confirms briefly. (~3–5s.)
- **Say next:** "So now it's holding my schedule, not me."

---

**④ You say:**
> "Okay — I just opened my slides. That's a real start."

- **Triggers:** `log_win` (and Buddy may `check_screen` to ground it)
- **Audience sees / hears:** Buddy celebrates the win in one warm line ("Nice — that's the hard part, you're moving"). Fast (~2s). Shows the ADHD body-double behaviour, not just tools.

---

**⑤ You say (the network flex / finale):**
> "One more. Get your orchestrator to spec out a simple one-page landing site for Buddy and hand it to the builder."

- **Triggers:** `ask_agent('orchestrator', …)` → orchestrator runs context → PRD → builder
- **Talk-track while it works (say this):** "This is the manager agent — it's writing a spec and handing it down the chain to a builder. One voice request just moved through three agents."
- **Audience sees:** the dark **Focus card** (the hero headline) rewrites itself to *"…landing site for Buddy"* and its **numbered steps populate** from the builder's plan. Buddy says it's specced and handed off. Biggest single visual change on the board. (~15–20s.)

---

**BOT WRAPS** — let Buddy end the call naturally, then deliver your close.

> **If you're short on time,** cut ④ (the win). ①→②→③→⑤ is the full story: network → real browser → memory → multi-agent build.

---

## 2) Backup one-liners — fast, visible, reliable

Use any of these if a beat stalls or you have spare time. Each is quick and produces a clear on-screen or spoken result.

- **"Buddy, what's the fastest way to unstick a task when I'm overwhelmed?"**
  → `ask_brain` — instant spoken reframe, no browser/container dependency. The safest fallback: always answers.

- **"Buddy, remind me to drink water at three PM."**
  → `ask_agent('bookkeeper', …)` — a new dated row lands in the **"Not now, but safe"** list. Fast and visibly changes the board.

- **"Buddy, who's on your team and what's each one good at?"**
  → `list_agents` — instant. Buddy reads the crew; it maps 1:1 to the **Your crew** card.

- **"Buddy, I just sent the email — mark that done."**
  → `log_win` — instant, warm celebration. Good energy filler while something else loads.

---

## 3) If it breaks — recovery lines (say naturally, buy time)

- If a tool is slow or silent:
  > "Give it a second — that's Buddy reaching across to another agent on the mesh. The round-trip is the honest part."

- If it errors or comes back empty:
  > "Looks like that one's thinking hard — let me ask it a simpler way." *(then fire a Backup one-liner, e.g. the `ask_brain` unstick question)*

- If Buddy rambles or goes off:
  > "Buddy — keep it to one line for me." *(the agent is tuned for short phone-call answers and will snap back)*

---

## 4) The pitch wrapper

**Open with (two sentences):**
> "This is Buddy — a calm, proactive co-pilot for anyone whose attention wanders, built as a network of small agents you talk to by voice. I'm going to have one live conversation, and you'll watch that voice ripple out to a browser, a bookkeeper, and a whole build chain — in real time."

**Close with (one sentence):**
> "One phone call, and the plan got researched, remembered, and built — Buddy stays with the task, so the person doesn't have to hold all of it."
