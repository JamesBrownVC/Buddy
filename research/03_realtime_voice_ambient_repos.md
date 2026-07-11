# 03 — Real-Time, Follow-Along, Voice-First Assistant: Open-Source Building Blocks

Research brief for the **Hermes ADHD Bridge** hackathon. Target platform: **Windows 11, Intel Arc GPU, no CUDA**. Priority is a low-latency, barge-in-capable, privacy-preserving voice agent that can "follow along" with what the user is doing on screen and remember context across sessions.

> Format per entry: **Name** — GitHub URL — *what it does* — **why relevant + how to use it tomorrow**.
> "CPU / Arc note" flags whether it runs without an NVIDIA GPU (critical for our hardware).

Date compiled: 2026-07-10. Verified via web search.

---

## TL;DR — Recommended hackathon stack

- **STT:** `faster-whisper` (small/base, int8, CPU) wrapped by **WhisperLive** for streaming, OR **Moonshine v2** if you want the lowest latency on short utterances. Vosk is the zero-dependency fallback.
- **TTS:** **Kokoro-82M** (best quality-for-latency on CPU, sub-0.3s), **Piper** as the ultra-light fallback, **NeuTTS Air** if you want voice cloning / a distinctive assistant voice.
- **VAD + turn-taking:** **Silero VAD** for speech/silence + **Pipecat** (with bundled `smart-turn-v3`) or **LiveKit Agents** as the orchestrator that handles barge-in for you. Don't hand-roll interruption.
- **Ambient screen context:** **screenpipe** (local, Windows-supported, accessibility-first text capture) for the "follow-along" awareness; `Python-UIAutomation-for-Windows` / `pywinauto` for lightweight active-window + focused-control reads if screenpipe is too heavy for a 24h build.
- **Memory:** **mem0** (drop-in memory layer, fastest to integrate) or **basic-memory** (Markdown + MCP, human-inspectable) for persistent user/ADHD context.
- **Differentiation vs prior art (Goblin Tools, Tiimo, Saner, Focusmate):** none of them are a *real-time voice companion that watches your screen and nudges you in the moment*. That's the gap Hermes fills — proactive, ambient, body-doubling-by-AI.

---

## 1. Low-Latency STT (Speech-to-Text)

The core constraint: **no CUDA**. Everything below can run on CPU; a few can offload to Intel Arc via OpenVINO/Vulkan.

### faster-whisper
- **URL:** https://github.com/SYSTRAN/faster-whisper
- **What:** Whisper reimplemented on CTranslate2; up to ~4x faster than `openai/whisper` at the same accuracy, with lower memory. Built-in VAD pipeline.
- **Why + tomorrow:** The default workhorse. On CPU use `small` or `base` with `compute_type="int8"` → ~0.5–2s behind live speech. `pip install faster-whisper`, feed 16kHz mono chunks. **CPU/Arc note:** CPU + CUDA only (no native Arc/Metal); on Arc you'd go through whisper.cpp/OpenVINO instead. For our box, run it int8 on CPU.

### whisper.cpp
- **URL:** https://github.com/ggml-org/whisper.cpp (formerly ggerganov/whisper.cpp)
- **What:** C/C++ port of Whisper with a `--stream` mode; runs on CPU, Metal, CUDA, **Vulkan, and OpenVINO**.
- **Why + tomorrow:** The one STT that can actually **use the Intel Arc GPU** (build with the OpenVINO or Vulkan backend). Reports of ~1s for short English on an Arc A380 with large-v2. Most memory-efficient on pure CPU too. Build once, call the streaming example or the server binary. Best choice if you want Arc acceleration tomorrow.

### whisper_streaming (UFAL)
- **URL:** https://github.com/ufal/whisper_streaming
- **What:** A streaming policy layer ("LocalAgreement") on top of Whisper backends (recommends faster-whisper) with self-adaptive latency.
- **Why + tomorrow:** If you want *research-grade* incremental/committed transcription without writing the chunking logic yourself. Wrap your faster-whisper model; gives stable partial hypotheses. Good for a "live captions" UI element.

### WhisperLive
- **URL:** https://github.com/collabora/WhisperLive
- **What:** Near-live Whisper server/client using faster-whisper as backend; websocket streaming, VAD built in.
- **Why + tomorrow:** Fastest path to a **working streaming mic→text service** in an afternoon. Run the server, connect the browser/Python client, get transcripts over a socket. Pairs cleanly with a JS front-end. Strong default for the demo.

### Vosk
- **URL:** https://github.com/alphacep/vosk-api
- **What:** Fully offline STT toolkit, ~50MB models, true streaming API with zero-latency partials, 20+ languages, Python/Node/C#.
- **Why + tomorrow:** The **zero-dependency, always-works fallback** — no GPU, tiny, deterministic, streaming out of the box. `pip install vosk`, download the small English model, feed the mic. Lower accuracy than Whisper but latency is excellent and it never fails to install. Great safety net for a hackathon.

### Moonshine (v2)
- **URL:** https://github.com/moonshine-ai/moonshine (also usefulsensors/moonshine)
- **What:** Very-low-latency ASR for edge devices; ONNX/`.ort` runtime, C++ core. v2 adds an "Ergodic Streaming Encoder" that caches encoder/decoder state to drive latency down.
- **Why + tomorrow:** **Lowest latency for short commands/utterances** and runs great on CPU/SBCs via ONNXRuntime. Ideal if the agent responds to quick spoken nudges ("done", "next", "snooze"). `pip install useful-moonshine` / ONNX package; wire to mic. **CPU/Arc note:** ONNXRuntime → runs on CPU everywhere; can target Intel via the OpenVINO EP.

### Deepgram (API — Nova-3 / Flux)
- **URL:** https://developers.deepgram.com/reference/speech-to-text/listen-streaming (docs; not open source)
- **What:** Hosted streaming STT over websockets; Nova-3 ~sub-300ms streaming latency; **Flux** is a voice-agent-specific model that folds in turn detection (saves 200–600ms vs STT+VAD).
- **Why + tomorrow:** The **latency/accuracy escape hatch** if local STT is too slow on the demo machine. Not local/private, needs an API key and network — so use only as a fallback or for the "wow" latency in a live demo. Flux is worth a look because it does endpointing for you.

**Category pick:** WhisperLive (streaming) over faster-whisper (int8 CPU) for the build; whisper.cpp+OpenVINO if you want to light up the Arc GPU; Vosk as the guaranteed fallback; Moonshine for snappy short-command handling.

---

## 2. Local TTS (Text-to-Speech)

Trade-off axis: **naturalness vs latency vs footprint**, all on CPU.

### Kokoro-82M
- **URL:** https://github.com/hexgrad/kokoro (model: huggingface.co/hexgrad/Kokoro-82M)
- **What:** Apache-2.0, 82M-param TTS; near-cloud quality for en-US/en-GB, 12+ voices, 8 languages, ONNX runtime.
- **Why + tomorrow:** **Best quality-per-latency on CPU** — consistently under ~0.3s for short text, GPU-free. This is the recommended assistant voice. `pip install kokoro` (or the ONNX build), pick a voice, stream sentences as they're generated. **CPU/Arc note:** CPU-fine; ONNX build can use OpenVINO EP on Arc.

### Piper
- **URL:** https://github.com/OHF-Voice/piper1-gpl (active; original https://github.com/rhasspy/piper archived read-only Oct 2025)
- **What:** Fast local neural TTS (VITS→ONNX, embedded espeak-ng), ~10–50M params, 44 languages, one voice per model file.
- **Why + tomorrow:** **Smallest footprint, most robust install** — the fallback voice that runs on literally anything, including a Raspberry Pi. Quality is "functional but a bit robotic." `pip install piper-tts`, download a voice `.onnx`, pipe text→wav. Use if Kokoro's install fights you. Note the license move to GPL-3.0 (piper1-gpl).

### NeuTTS Air
- **URL:** https://github.com/neuphonic/neutts-air (org: https://github.com/neuphonic/neutts)
- **What:** On-device 0.5B-LLM-backbone TTS with **instant voice cloning from ~3s of audio**; ships in GGML, uses the NeuCodec 50Hz codec; runs on phones/laptops/Pi.
- **Why + tomorrow:** Gives Hermes a **distinctive, optionally cloned voice** (e.g., a calm coach voice) fully offline. GGML = runs via llama.cpp-style CPU inference. Heavier than Kokoro but the cloning + "real-time on-device" story is a great demo hook. Use if voice personality is a selling point.

### Coqui / XTTS v2
- **URL:** https://github.com/idiap/coqui-ai-TTS (maintained fork of the archived coqui-ai/TTS)
- **What:** Multilingual (17 lang) zero-shot voice cloning from a ~6s sample; can stream at <200ms latency.
- **Why + tomorrow:** Strongest **open voice-cloning** quality and streaming, but realistically wants a GPU/8GB for real-time — **on CPU-only it's likely too slow for live back-and-forth**. Keep for offline pre-generation of canned prompts, or if a GPU appears. Otherwise prefer Kokoro/NeuTTS.

### StyleTTS 2
- **URL:** https://github.com/yl4579/StyleTTS2
- **What:** Diffusion + adversarial zero-shot TTS; SOTA naturalness and style transfer; competitive with / occasionally beating XTTS on cloning quality.
- **Why + tomorrow:** Highest naturalness ceiling, but **heaviest and slowest to set up** — not a 24h-hackathon real-time pick. Note it as the "quality frontier" and skip for the live loop unless you have spare time and a GPU.

**Category pick:** Kokoro-82M as the default assistant voice (quality + sub-0.3s CPU), Piper as the bulletproof fallback, NeuTTS Air if a signature/cloned voice is part of the pitch.

---

## 3. Voice Activity Detection & Turn-Taking (barge-in is the whole game for "follow-along")

A follow-along agent MUST let the user interrupt it mid-sentence. Use a VAD for raw speech/silence, a **semantic turn detector** for "are they actually done," and an **orchestrator** that cancels TTS on barge-in. Don't build interruption logic yourself.

### Silero VAD
- **URL:** https://github.com/snakers4/silero-vad
- **What:** Tiny, fast, enterprise-grade neural VAD; classifies audio frames as speech/silence in real time; ~1ms/chunk on CPU.
- **Why + tomorrow:** The **de-facto VAD** — bundled natively in both LiveKit Agents and Pipecat. Detects when the user starts talking so you can pause/cancel the agent's speech (barge-in trigger). `pip install silero-vad` or let the orchestrator auto-provision it. CPU-only, trivial.

### smart-turn (v2 / v3) by Pipecat
- **URL:** https://github.com/pipecat-ai/smart-turn (weights: huggingface.co/pipecat-ai/smart-turn-v3)
- **What:** Open-source **semantic VAD** — decides if a speaker has *finished their turn* from the raw waveform (intonation, not transcript). v2 is multilingual (14 lang), ~360MB, ~12ms inference; v3 smaller/faster and **bundled with Pipecat** (no separate download).
- **Why + tomorrow:** Kills the classic "agent interrupts you when you pause to think" problem — huge for ADHD users who trail off mid-sentence. Enable `LocalSmartTurnAnalyzerV3` in Pipecat; runs locally. BSD-2 license.

### Pipecat
- **URL:** https://github.com/pipecat-ai/pipecat
- **What:** Python framework for real-time voice (and multimodal) agents — a pipeline of STT→LLM→TTS frames with built-in VAD, interruption, and turn analysis.
- **Why + tomorrow:** **Fastest way to a full barge-in-capable voice loop in Python.** Its `VADStopFrame` / interruption handling cancels TTS the instant the user speaks. Swap in local faster-whisper + Kokoro + Silero + smart-turn as plug-in services. Best fit if the team is Python-first. Start from a `pipecat` quickstart example and replace the cloud services with local ones.

### LiveKit Agents
- **URL:** https://github.com/livekit/agents
- **What:** Framework for realtime voice/video AI agents over WebRTC; `AgentSession` auto-provisions Silero VAD + a transformer-based **semantic turn detector**; first-class interruption handling.
- **Why + tomorrow:** Use if you want a **browser/WebRTC front-end** and robust multi-user audio transport out of the box. It keeps turn detection live during agent playback (proper barge-in) and cancels TTS on user speech. Heavier infra (a LiveKit server) than Pipecat, but excellent if the demo is web-based. Pluggable local STT/TTS.

**Category pick:** Silero VAD (raw) + smart-turn-v3 (semantic) inside **Pipecat** for a Python build, or **LiveKit Agents** if you want WebRTC/browser. Both give you barge-in for free — that is the single most important feature for a "follow-along" feel.

---

## 4. Screen / Ambient Context Capture (the "follow-along" awareness) — local & privacy-preserving only

The agent needs to know *what the user is doing* to nudge relevantly. Two tiers: full ambient recorders (screenpipe) vs. lightweight Windows accessibility reads (pywinauto/UIA).

### screenpipe
- **URL:** https://github.com/screenpipe/screenpipe (historically mediar-ai/screenpipe)
- **What:** Continuously captures screen + audio 24/7 into a **local, searchable** store; accessibility-first text extraction with OCR fallback; natural-language search filtered by app, window title, browser URL, time. MIT, no cloud by default, works with local Ollama.
- **Why + tomorrow:** **The flagship "ambient context" engine** and it runs on Windows. Gives Hermes a live feed of on-screen text so it can say "you've been on Twitter for 20 min, want to get back to the report?" ~5–10% CPU (event-driven, only processes on change). Run the app, query its local API/SDK for recent screen text. Privacy story is strong (fully auditable, on-device).

### OpenRecall
- **URL:** https://github.com/openrecall/openrecall
- **What:** Open-source, privacy-first alternative to Windows Recall / Rewind — periodic screenshots + OCR + semantic timeline search, all local.
- **Why + tomorrow:** Lighter, simpler, Python-based alternative to screenpipe if you just need "what was on screen recently" without the audio pipeline. Good if screenpipe's Rust/Tauri stack is fiddly to build in time. Cross-platform incl. Windows.

### Windows UI Automation (Microsoft accessibility API)
- **URL (Python wrapper):** https://github.com/yinkaisheng/Python-UIAutomation-for-Windows
- **What:** Python 3 wrapper over Microsoft UI Automation — read the accessibility tree of any app (WinForms, WPF, Qt, Electron, Chrome, Firefox), get focused control, window title, text content.
- **Why + tomorrow:** The **lightweight, precise, low-overhead** way to know exactly what the user is focused on *right now* (active field, selected text, current doc) without recording everything. Far cheaper than OCR and more accurate. Poll active window + focused element in a background thread. Best "just enough context" option for a 24h build.

### pywinauto
- **URL:** https://github.com/pywinauto/pywinauto
- **What:** Windows GUI automation based on Win32 + UI Automation backends; can read text from controls and enumerate windows via the `Desktop` object.
- **Why + tomorrow:** Alternative/companion to the UIA wrapper for **active-window + control-text** monitoring, plus it can *act* (focus a window, click) — useful if Hermes should gently bring a task window to front. `pip install pywinauto`, use `backend="uia"`. Pairs well with the raw UIA wrapper above.

### Active-window + clipboard watchers (DIY primitives)
- **Foreground window:** `pygetwindow` / `pywin32` `GetForegroundWindow` for a 1-line "what app is focused."
- **Clipboard:** `pyperclip` / `win32clipboard` to watch copies (a strong intent signal — user just copied an error message, a URL, a task).
- **Why + tomorrow:** These are 10-line watchers that give surprisingly rich context (app switches, copy events) with near-zero overhead and no privacy footprint. Cheapest possible "ambient sensing" to ship first, then layer screenpipe/UIA on top.

**Category pick:** `Python-UIAutomation-for-Windows` (+ active-window/clipboard watchers) for a fast, precise, low-footprint "what are you doing now" signal; add **screenpipe** for the richer searchable timeline / "you've been distracted" narrative if time allows. All fully local.

---

## 5. Memory / Second-Brain (persistent user & ADHD context)

The agent must remember goals, routines, what derails the user, and prior sessions — without re-asking.

### mem0
- **URL:** https://github.com/mem0ai/mem0
- **What:** Universal memory layer for AI agents; extracts, stores, and retrieves salient facts/preferences; hybrid vector + graph; simple `add()` / `search()` API.
- **Why + tomorrow:** **Fastest memory to integrate** — a few lines to give Hermes long-term recall of user preferences and patterns. Can run **fully local** (local LLM + local vector store like Qdrant/Chroma). `pip install mem0ai`, point it at a local embedder. Best default for a hackathon.

### Letta (formerly MemGPT)
- **URL:** https://github.com/letta-ai/letta
- **What:** Stateful-agent runtime with hierarchical (core/archival) memory that self-edits over time; memory is a first-class primitive, not a bolt-on.
- **Why + tomorrow:** Use if you want the *agent itself* to manage what it remembers/forgets (e.g., promote "user always skips the gym on Mondays" to core memory). Heavier — it's a whole agent server — so adopt only if memory management is central to the pitch, not just storage. Runs with local models.

### basic-memory
- **URL:** https://github.com/basicmachines-co/basic-memory
- **What:** Persistent semantic knowledge graph stored as **plain Markdown files on disk**, synced to a SQLite/Postgres index (FastEmbed hybrid full-text + vector search); exposed to any LLM over **MCP**; integrates with Obsidian.
- **Why + tomorrow:** Best when you want memory that is **human-inspectable and user-owned** (great trust story for ADHD users who want to see/edit what the assistant "knows"). Point it at a folder, wire via MCP. The notes double as the user's own second brain. Local by default.

### Khoj
- **URL:** https://github.com/khoj-ai/khoj
- **What:** Self-hostable personal AI that indexes your notes/docs (Markdown, PDF, Org, Obsidian, etc.) for semantic search and chat; can run fully offline with local models.
- **Why + tomorrow:** If the user already keeps notes, Khoj turns them into retrievable context for Hermes. More of a full app than a library — use its API as a retrieval backend, or as inspiration for the "chat with your own notes" surface. Self-host locally.

### Reor
- **URL:** https://github.com/reorproject/reor
- **What:** Local-first, AI-native desktop **note-taking app** (Ollama + local vector DB) that auto-links related notes.
- **Why + tomorrow:** Less a component, more a reference design for a local second-brain UI. Consider if Hermes has a notes surface; otherwise borrow the "auto-connect related thoughts" idea. Fully local.

### Vector-store primitives (roll-your-own)
- **Chroma** (https://github.com/chroma-core/chroma) or **Qdrant** (https://github.com/qdrant/qdrant) + a local embedder (FastEmbed / `sentence-transformers` / Ollama `nomic-embed-text`).
- **Why + tomorrow:** If you don't want a memory framework's opinions, a local vector DB + embeddings is a 30-minute persistent-context store you fully control. Good backend under mem0 too.

**Category pick:** **mem0** for speed of integration; **basic-memory** if the "user can see and own their memory" trust angle matters for the ADHD demographic. Both run local.

---

## 6. Prior-Art ADHD / Focus Tools (inspiration & the gap Hermes fills)

Not open-source components — these are the incumbents. Study what they nail and where a **real-time, voice-first, screen-aware companion** beats them.

### Goblin Tools ("Magic ToDo")
- **URL:** https://goblin.tools
- **What:** Free AI toolkit; flagship "Magic ToDo" breaks any task into bite-sized steps; also tone-adjuster, time-estimator ("Judge").
- **Gap Hermes fills:** Goblin is one-shot and text-only — you go to it. Hermes can **decompose a task out loud, in the moment**, then *watch you start step 1* and body-double you through it. Borrow the task-breakdown UX; add real-time follow-through.

### Saner.ai
- **URL:** https://saner.ai
- **What:** AI personal assistant for ADHD adults / knowledge workers — unifies tasks, notes, email, and AI-assisted organization in one place.
- **Gap Hermes fills:** Saner is a dashboard you manage. Hermes is **ambient and proactive** — it notices you drifted and nudges by voice, no app to open. Complementary: Saner-style capture + Hermes-style in-the-moment coaching.

### Tiimo
- **URL:** https://www.tiimoapp.com
- **What:** Visual, neurodivergent-first daily planner with timers, visual schedules, and routines; co-designed with ADHD/autistic communities.
- **Gap Hermes fills:** Tiimo is a beautiful *plan*, but the plan still needs a human to follow it. Hermes is the **voice that keeps you on the plan in real time** and adapts when you fall off it. Borrow the calm, visual-timer aesthetic.

### Llama Life
- **URL:** https://llamalife.co
- **What:** Timeboxing app that puts a timer on **one task at a time** to fight overwhelm and time-blindness.
- **Gap Hermes fills:** Same single-task-focus philosophy, but Hermes delivers it **hands-free by voice** and can auto-start the next timer / check in verbally instead of you tapping. Borrow the one-task-at-a-time discipline.

### Focusmate (body doubling)
- **URL:** https://www.focusmate.com
- **What:** Live video "body doubling" — pairs you with a real human for a scheduled quiet co-working session to beat task paralysis and isolation.
- **Gap Hermes fills:** This is the **most important reference.** Focusmate proves body doubling works but requires scheduling and another human. Hermes is an **always-available AI body-double** — the core value prop. Match the "someone is here with you, gently accountable" feeling; remove the scheduling friction.

### Sunsama
- **URL:** https://www.sunsama.com
- **What:** Calm daily planner that pulls tasks from all your tools into a deliberate daily plan with reflection rituals.
- **Gap Hermes fills:** Sunsama is a mindful *planning* ritual; it stops once the day starts. Hermes is the **execution-time companion** that carries the plan through the day by voice. Borrow the daily-plan + evening-reflection loop as Hermes conversation moments.

**Positioning summary:** The incumbents cover *planning* (Sunsama, Tiimo, Llama Life), *task-breakdown* (Goblin), *capture/organization* (Saner), and *human accountability* (Focusmate). **None is a real-time, voice-first, screen-aware AI body-double that nudges you in the moment.** That intersection — ambient sensing + proactive voice + body-doubling presence — is the whitespace Hermes owns.

---

## Sources
- faster-whisper — https://github.com/SYSTRAN/faster-whisper
- whisper.cpp — https://github.com/ggml-org/whisper.cpp ; OpenVINO/Arc notes — https://blog.openvino.ai/blog-posts/optimizing-whisper-and-distil-whisper-for-speech-recognition-with-openvino-and-nncf
- whisper_streaming — https://github.com/ufal/whisper_streaming
- WhisperLive — https://github.com/collabora/WhisperLive
- Vosk — https://github.com/alphacep/vosk-api ; https://alphacephei.com/vosk/
- Moonshine — https://github.com/moonshine-ai/moonshine
- Deepgram streaming — https://developers.deepgram.com/reference/speech-to-text/listen-streaming
- Kokoro — https://github.com/hexgrad/kokoro ; https://huggingface.co/hexgrad/Kokoro-82M
- Piper — https://github.com/OHF-Voice/piper1-gpl ; https://github.com/rhasspy/piper
- NeuTTS Air — https://github.com/neuphonic/neutts-air
- Coqui/XTTS — https://github.com/idiap/coqui-ai-TTS
- StyleTTS2 — https://github.com/yl4579/StyleTTS2
- Silero VAD — https://github.com/snakers4/silero-vad
- smart-turn — https://github.com/pipecat-ai/smart-turn ; https://huggingface.co/pipecat-ai/smart-turn-v3
- Pipecat — https://github.com/pipecat-ai/pipecat
- LiveKit Agents — https://github.com/livekit/agents ; https://livekit.com/blog/turn-detection-and-interruption-handling
- screenpipe — https://github.com/screenpipe/screenpipe
- OpenRecall — https://github.com/openrecall/openrecall
- Python-UIAutomation-for-Windows — https://github.com/yinkaisheng/Python-UIAutomation-for-Windows
- pywinauto — https://github.com/pywinauto/pywinauto
- mem0 — https://github.com/mem0ai/mem0
- Letta — https://github.com/letta-ai/letta
- basic-memory — https://github.com/basicmachines-co/basic-memory
- Khoj — https://github.com/khoj-ai/khoj
- Reor — https://github.com/reorproject/reor
- ADHD prior art — Goblin Tools (goblin.tools), Saner.ai, Tiimo, Llama Life, Focusmate, Sunsama
