# The Scientific Foundation for an ADHD ↔ Neurotypical "Bridge" Agent

**Project:** Hermes — an AI agent that follows along in real time, externalizes working memory, and reduces daily executive-function friction for the ADHD brain.
**Purpose of this doc:** Translate the cognitive-science and clinical evidence base into concrete, buildable agent features.
**Date:** 2026-07-10

> **How to read this:** Every finding is followed by a **→ Agent feature** translation. Sources are inline as URLs; peer-reviewed papers are prioritized, with reputable clinical bodies (CHADD, NICE, ADDitude) cited for practice. A confidence tag (**[Strong]** / **[Moderate]** / **[Emerging/anecdotal]**) marks how solid the evidence is, because honest design depends on knowing which claims are load-bearing.

---

## 1. Core ADHD Executive-Function Deficits

ADHD is best understood not as a deficit of *attention* but as a disorder of *self-regulation and executive function* — the brain's ability to hold goals in mind, manage time, initiate action, and regulate emotion. Barkley's influential model frames the core impairment as **behavioral disinhibition** producing downstream executive deficits, and reframes ADHD as fundamentally a *time-based / temporal information-processing* disorder rather than a pure attention deficit ([Willcutt et al. 2005, *Biol Psychiatry*, meta-analytic review of the EF theory of ADHD](https://www.sciencedirect.com/science/article/abs/pii/S000632230500171X)).

### 1.1 Working memory **[Strong]**
Working memory (holding and manipulating information over seconds) is arguably the single most common EF deficit in ADHD. Meta-analytic between-group effect sizes are large, roughly **d ≈ 0.69–0.74**, and *spatial/visuospatial* working memory is even more impaired than verbal ([Martinussen et al. / moderators of WM deficits meta-analysis, *Neurosci Biobehav Rev*](https://sciencedirect.com/science/article/abs/pii/S0272735812000979); [Frontiers in Psychiatry 2024, WM & inhibition in ADHD](https://www.frontiersin.org/journals/psychiatry/articles/10.3389/fpsyt.2024.1277583/full)). Notably, WM and inhibition dissociate: ~46% of children with ADHD have WM deficits *without* inhibition deficits, so WM is a distinct, primary target — not merely "downstream" of impulsivity ([Frontiers 2024](https://www.frontiersin.org/journals/psychiatry/articles/10.3389/fpsyt.2024.1277583/full)).
- **→ Agent feature:** Be the user's **external working-memory buffer**. Persistently display the *one* current task, the "why," and the immediate next micro-step so nothing has to be held in the head. On any interruption, snapshot the mental context and restore it verbatim on return ("Here's exactly where you were: …"). Favor *visual/spatial* externalization (boards, spatial layout) since visuospatial WM is the harder-hit channel.

### 1.2 Task initiation & delay aversion **[Strong]**
ADHD "procrastination" is largely a **task-initiation** failure — inability to *start* despite knowing what to do, wanting to do it, and understanding the cost — not laziness or intentional delay. It is driven partly by **delay aversion** (Sonuga-Barke): a heightened preference for immediate over delayed reward, so tasks with distant payoff feel aversive to begin ([Task initiation in ADHD — the science of why starting feels impossible](https://positivereseteatontown.com/task-initiation-adhd-understanding-the-science-behind-why-starting-feels-impossible/); [ADHD & procrastination as a task-initiation/activation problem](https://www.coachingwithbrooke.com/post/adhd-procrastination-is-the-most-misunderstood-neurological-phenomenon)).
- **→ Agent feature:** Attack **activation energy**, not motivation. Auto-shrink the first step to something absurdly small ("open the doc and type the title") and offer a one-tap "start the 2-minute version." Manufacture *immediacy* for delayed-reward tasks: nearer deadlines, visible countdowns, instant micro-rewards on step completion.

### 1.3 Time blindness / time perception **[Strong]**
People with ADHD show consistent deficits in **time estimation, time reproduction, and time discrimination**. A meta-analysis of 25 studies (n≈1,633) found a *medium* effect-size deficit in time discrimination, and 8 studies (n≈1,024) found a small-to-medium increase in time-estimation error ([adhdevidence.org meta-analysis summary](https://www.adhdevidence.org/blog/time-blindness-found-to-be-a-consistent-feature-of-adhd)). Deficits appear in childhood and remain stable into adulthood ([Time Perception in Adult ADHD: Findings from a Decade — A Review, 2023, PMC9962130](https://pmc.ncbi.nlm.nih.gov/articles/PMC9962130/); [Time perception as a focal symptom of adult ADHD, PMC8293837](https://pmc.ncbi.nlm.nih.gov/articles/PMC8293837/)). Practically: time is felt as "now" vs "not now," and elapsed time is chronically underestimated.
- **→ Agent feature:** Make time **ambient and visible**. Show elapsed-time and time-remaining as a persistent visual (shrinking bar, analog dial), not a number to be recalled. Before any task ask the user to *guess* duration, then log actuals to gently recalibrate future estimates. Convert vague "later" into concrete anchored times, and give staged pre-event alerts (see §3, NICE 24h/2h/15min pattern).

### 1.4 Prospective memory ("remembering to remember") **[Moderate–Strong]**
Prospective memory (PM) — remembering to *do a planned action in the future* — is impaired in ADHD, and the impairment is far larger in **everyday life** than in the lab ([Complex prospective memory in adults with ADHD, Altgassen et al., *PLOS One* 2013](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0058338)). Crucially, PM *partially mediates* the link between ADHD symptoms and procrastination ([Prospective memory (partially) mediates ADHD → procrastination, *ADHD Atten Def Hyp Disord* 2019](https://link.springer.com/article/10.1007/s12402-018-0273-x)). The deficit is selective: **time-based** PM ("do X at 3pm") is impaired, while **event-based** PM ("do X when you see the cue") is relatively spared ([activity-/event-based PM in ADHD, PMC10255685](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10255685/)).
- **→ Agent feature:** Own the "remembering to remember" entirely — the user should never rely on internal PM. **Convert fragile time-based intentions into robust event/context-based cues**: instead of "9am: email Sam," fire "You just opened your laptop → email Sam" (location, app-open, calendar-adjacency, or activity as the trigger). This exploits the spared event-based channel.

### 1.5 Emotional dysregulation (DESR) **[Strong]**
Deficient emotional self-regulation (DESR) is now considered a **core**, not peripheral, feature of ADHD. Emotional-regulation deficits are evident in **34–70% of adults** and **25–45% of children** with ADHD (Shaw et al. 2014 review), and a systematic review concludes emotion dysregulation is a core symptom of adult ADHD ([Evidence of emotion dysregulation as a core symptom of adult ADHD: a systematic review, *PLOS One*, PMC9821724](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9821724/); [Barkley on DESR, ADDitude](https://www.additudemag.com/desr-adhd-emotional-regulation/)). The mechanism: weak inhibition means emotionally-charged reactions aren't buffered before they drive behavior.
- **→ Agent feature:** Be **co-regulating, never escalating**. Detect friction/frustration signals (rapid task abandonment, self-critical language) and respond with grounding and reframing, not more demands. Offer a "this feels big — want to shrink it or take a 5-min reset?" off-ramp. Design every message assuming an emotionally-loaded moment.

### 1.6 Task-switching cost / set-shifting **[Moderate]**
ADHD is associated with **medium-magnitude** shifting/cognitive-flexibility impairments and larger, more variable **switch costs** ([Meta-analytic study on shifting & cognitive flexibility in ADHD, TAMU OAKTrust](https://oaktrust.library.tamu.edu/items/34286518-459e-48b5-99f9-ab36ba927dac)), though some studies argue the deficit is not *unique* to shifting but part of broader EF variability ([Do children with ADHD have set-shifting deficits? PubMed 30945912](https://pubmed.ncbi.nlm.nih.gov/30945912/)). Either way, each context switch is expensive and interruptions are costly to recover from.
- **→ Agent feature:** **Minimize and cushion switches.** Batch similar tasks, protect single-task focus windows, and — the highest-value move — provide **interruption recovery**: when the user returns from a distraction, restore the full context (open files, last line of thought, next step) so re-entry cost approaches zero.

### 1.7 The "Wall of Awful" **[Emerging/clinical construct]**
Coined by ADHD coach **Brendan Mahan**, the *Wall of Awful* is the accumulated **emotional barrier** — built from bricks of past failure, shame, disappointment, and rejection — that stands between a person and a task. Because people with ADHD fail (and are corrected) more often, their walls are larger, and the wall, not the task itself, is what blocks initiation. The remedy is to change *emotional state* ("put a door in the wall") rather than push harder ([The Wall of Awful — ADHD Essentials](http://www.thewallofawful.com/the-wall-of-awful/); [5 Ways to Overcome the Wall of Awful (PDF)](https://www.adhdessentials.com/wp-content/uploads/5-Ways-to-Overcome-The-Wall-of-Awful.pdf)).
- **→ Agent feature:** Treat avoidance as an **emotional** signal, not a productivity failure. When a task keeps getting deferred, don't re-nag — name the wall gently ("this one's got some weight on it, huh?"), lower the stakes, and offer a state-shift (music, a walk, or "let's just look at it together for 60 seconds"). Never pile shame bricks onto the wall.

### 1.8 Rejection-Sensitive Dysphoria (RSD) **[Emerging — clinical, not a formal diagnosis]**
RSD, popularized by psychiatrist **William Dodson**, describes extreme, sudden emotional pain triggered by *perceived* rejection, criticism, or falling short — often experienced as physical ("like being punched in the chest"). It's framed as a manifestation of ADHD emotional dysregulation and can drive either people-pleasing or total avoidance of anything with failure risk ([RSD & ADHD, ADDitude/Dodson](https://www.additudemag.com/rejection-sensitive-dysphoria-and-adhd/)). **Honest caveat:** RSD is *not* a DSM diagnosis and is under-researched empirically — treat it as a clinically-useful lens, not established fact ([Rejection Sensitivity Dysphoria: the actual research, *Psychology Today*](https://www.psychologytoday.com/us/blog/if-i-be-waspish/202604/rejection-sensitivity-dysphoria-the-actual-research)).
- **→ Agent feature:** **RSD-safe tone by default.** Never frame missed tasks as failures, never use red "overdue"/streak-breaking shame mechanics, never imply disappointment. Corrections and nudges must be non-judgmental, collaborative, and face-saving. This is a hard tone constraint on *every* string the agent emits.

---

## 2. Cognitive Offloading / Externalization — Evidence + Dependency Risk

The core scientific premise of the whole project: offloading cognition to reliable external tools measurably improves performance for exactly the functions ADHD impairs.

**It works, and the effect is large. [Strong]** Cognitive offloading is "the use of physical action to alter the information-processing requirements of a task so as to reduce cognitive demand" (Risko & Gilbert, 2016, *Trends in Cognitive Sciences*). In a canonical prospective-memory paradigm, unaided forgetting runs ~**45%**, but drops to ~**5% with external reminders** — a near-tenfold improvement; accuracy typically rises from 50–60% unaided to 90–100% with reminders ([Outsourcing memory to external tools: a review of intention offloading, Gilbert et al., *Psychon Bull Rev* 2023, PMC9971128](https://pmc.ncbi.nlm.nih.gov/articles/PMC9971128/)).

**The decision to offload is *metacognitive*. [Strong]** People offload more when they *believe* their memory is inadequate — and this is driven by **subjective confidence independent of actual ability**. When beliefs diverge from real accuracy, confidence still predicts offloading ([Gilbert et al. 2023, PMC9971128](https://pmc.ncbi.nlm.nih.gov/articles/PMC9971128/)). This matters for ADHD: chronically low confidence in one's own memory is *adaptive* here — it should route to the tool.
- **→ Agent feature:** Make offloading **frictionless and trustworthy** so the user's brain grants itself "permission to forget." The agent must be so reliable that the user stops trying to remember at all — capture must be instant, and nothing captured is ever lost.

**But there are real dependency risks. [Moderate]**
1. *What's reliably externalized tends not to be internalized* — offloading boosts immediate performance but can diminish unaided memory for the offloaded content ([Consequences of cognitive offloading: boosting performance but diminishing memory, PMC8358584](https://pmc.ncbi.nlm.nih.gov/articles/PMC8358584/)).
2. *Strategy perseveration* — prior reminder use biases future reliance, risking over-dependence and abandonment of one's own strategies ([Gilbert et al. 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC9971128/)).
3. *Manipulation/trust risk* — an untrustworthy external store can implant false memories ([Offloading memory leaves us vulnerable to memory manipulation, *Cognition*](https://www.sciencedirect.com/science/article/abs/pii/S0010027719301076)).

**The honest counterweight:** Gilbert et al. explicitly argue that for people with genuine memory/EF limitations, *foregoing effective reminders is more damaging than using them.* For an ADHD assistive tool, **offloading is the point** — the goal is functional capability, not memory training. Dependency concerns are real but secondary; they inform *how* the tool fades support, not *whether* to offload.
- **→ Agent feature:** Offload aggressively for daily function, but build in optional **scaffolding/fading**: occasionally let the user recall the next step before revealing it, and surface patterns ("you've built this routine 5 days running") so the user internalizes systems where they *can*, without ever penalizing reliance on the tool.

---

## 3. Evidence-Based Interventions → Features

### 3.1 Implementation intentions (if-then plans) **[Strong — best evidence here]**
"If [situation], then I will [action]" plans link a cue to a behavior and hand off initiation to automatic cue-detection, removing the deliberation moment. Meta-analysis across 94 tests: **d ≈ 0.65** (medium-large) on goal attainment ([Gollwitzer & Sheeran 2006, meta-analysis PDF](https://cancercontrol.cancer.gov/sites/default/files/2020-06/goal_intent_attain.pdf)). Effects are larger when the plan is genuinely *contingent* (if-then format), the person is motivated, and the plan is rehearsed at least once. Critically, this works *specifically* for populations with action-control problems: implementation intentions **improve response inhibition in children with ADHD** ([Gawrilow & Gollwitzer, *Cognit Ther Res* 2008](https://link.springer.com/article/10.1007/s10608-007-9150-1)), and a 2025 meta-analysis confirms small-to-medium benefits in children including executive-functioning outcomes ([Breitwieser et al., *Br J Psychology* 2025](https://bpspsychub.onlinelibrary.wiley.com/doi/10.1111/bjop.70065)).
- **→ Agent feature:** An **if-then plan builder**. Whenever a user sets a goal, the agent co-authors a contingent plan tied to a concrete cue ("*If* it's 9am and I've made coffee, *then* I open the report"), rehearses it once, and later fires on the cue. This is the highest evidence-to-effort feature in the whole set.

### 3.2 Task decomposition / chunking **[Strong mechanism, clinical consensus]**
Breaking a task into 5–15-minute sub-steps lowers **activation energy** to begin, keeps each step within limited working-memory capacity, and delivers a **dopamine hit per completed chunk** that fuels the next step ([ADHD task-chunking strategies](https://careclinic.io/adhd-task-chunking-strategies/); [chunking & why it helps / when it doesn't, The ADHD Space](https://www.adhdspace.ca/blog/adhd-procrastination-tools-that-actually-work-why-chunking-helps-and-when-it-doesnt)). Decomposition also *externalizes the planning* that impaired EF struggles to do internally — the user no longer has to figure out "what's next," they just follow the list.
- **→ Agent feature:** **One-tap auto-decomposition.** User names a task ("do taxes"); the LLM returns a concrete first-step-sized checklist (each step ≤15 min, first step trivially small), shown one-at-a-time to avoid overwhelm. Celebrate each check-off (the dopamine loop).

### 3.3 Time-boxing / Pomodoro **[Moderate — sound rationale, thin ADHD-specific RCTs]**
Fixed work intervals + breaks (classically 25/5) externalize time and reduce the "infinite task" dread. A running timer **increases awareness of passing time** — directly compensating for time blindness (§1.3) — and short bursts lower the barrier to start ([Adapting the Pomodoro technique for ADHD, PsychCentral](https://psychcentral.com/adhd/how-to-adapt-the-pomodoro-technique-adhd)). Note: rigorous ADHD-specific trials are limited; intervals often need shortening for ADHD.
- **→ Agent feature:** A **flexible focus-timer / co-working sprint** with a *visible* countdown, user-adjustable interval length, and gentle break prompts. Pair it with body doubling (§3.4).

### 3.4 Body doubling **[Emerging/anecdotal — plausible mechanism]**
Working in the presence of another person (who need not help) improves initiation and focus via social facilitation, implicit accountability, and co-regulation — "externalizing the activation and monitoring that impaired EF makes costly to generate internally." Evidence is largely anecdotal/community-based, but a recent VR study found participants finished tasks **faster** and reported greater sustained attention with **either a human *or an AI* body double** vs working alone ([Designing body doubling for ADHD in VR, arXiv 2509.12153](https://arxiv.org/abs/2509.12153); [Body doubling for ADHD overview, Medical News Today](https://www.medicalnewstoday.com/articles/body-doubling-adhd)).
- **→ Agent feature:** A **"work with me" presence mode** — the agent acts as an ambient co-worker: a soft "I'm here, working alongside you" state, periodic low-key presence pings, and a start/stop ritual. The VR finding that an *AI* double works is direct evidence this is viable for an agent.

### 3.5 Just-in-time prompting (JITAI) **[Strong framework]**
Just-In-Time Adaptive Interventions deliver "the right type/amount of support, at the right time" by adapting to the person's changing state, and — critically — only when the user is both **vulnerable AND receptive** ([Nahum-Shani et al., *Ann Behav Med* 2018](https://academic.oup.com/abm/article/52/6/446/4733473)). The corollary is a warning: *generic, non-adaptive reminders underperform.* A randomized trial of extra SMS reminders in an ADHD internet intervention found **no effect on module completion or login rates** ([Nordby et al., *Front Digit Health* 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9149073/)). Dumb reminders don't work; *contextual* ones do.
- **→ Agent feature:** **Context-aware nudging, not clock-based spam.** Fire prompts on state/context triggers (idle-after-planning, calendar adjacency, app-open, detected stuck-ness) and suppress them when the user is in flow or clearly unreceptive. Adapt frequency to what the user actually acts on.

### 3.6 Gentle accountability vs nagging **[Moderate — CHADD/coaching evidence]**
Structured, collaborative accountability is the active ingredient in ADHD coaching, which specifically targets planning, time management, and follow-through; coaches "hold clients accountable" while providing encouragement and non-judgmental feedback ([Evidence-based coaching for adults with ADHD, CHADD](https://chadd.org/attention-article/evidence-based-coaching-for-adults-with-adhd/)). The evidence base is stronger in student populations, smaller for general adults — accountability *works*, but only in a supportive, non-punitive frame.
- **→ Agent feature:** **Opt-in check-ins** ("want me to check back at 2pm?") with a warm, curious tone ("how'd the report go?") rather than "YOU MISSED YOUR TASK." Accountability is offered and consented-to, never imposed.

### 3.7 Reducing initiation friction / environmental modification **[Strong — clinical guideline]**
NICE guidance recommends **environmental modifications *before* medication** when symptoms still impair, explicitly including staged reminders (e.g., **24 hours, 2 hours, and 15 minutes** before important events), written instructions, and reduced-distraction workspaces ([NICE NG87 / *ADHD: diagnosis and management*, NBK493361](https://www.ncbi.nlm.nih.gov/books/NBK493361/)). This is the clinical mandate for exactly the kind of scaffolding an agent provides.
- **→ Agent feature:** **Staged, multi-horizon alerts** for commitments (24h / 2h / 15min) so a single reminder isn't a single point of failure; convert verbal/implicit tasks into written, structured items automatically; strip friction from every start (pre-fill, pre-open, one tap).

### 3.8 Capturing intrusive / tangential thoughts **[Strong mechanism]**
Unfinished tasks and open loops produce **intrusive thoughts** (the Zeigarnik effect) that hijack attention and working memory. The key relief finding: simply making a **concrete plan** for an unfinished task — *without doing it* — significantly reduces the intrusive thoughts, because the brain "needs to trust the task is handled," not that it's done (Masicampo & Baumeister; [Zeigarnik effect & closing loops](https://www.timestream.app/blog/the-zeigarnik-effect-why-unfinished-tasks-weigh-on-your-mind-and-how-to-close-loops)). Externalizing everything ("brain dump") grants "permission to forget."
- **→ Agent feature:** **Instant frictionless capture** — a single always-available input (voice or one keystroke) that swallows any stray thought/idea/task mid-flow, auto-files it, and *confirms it's handled* so the loop closes and the user returns to focus. This is the literal implementation of "externalize working memory."

---

## 4. Design Pitfalls & Ethics

An all-day "follow-along" agent for an emotionally-sensitive population is an ethics-dense product. Empirical design guidance from a study of an ADHD support assistant (**"Tether," for software engineers with ADHD**, [arXiv 2509.01946](https://arxiv.org/abs/2509.01946)) plus assistive-tech ethics converge on the following.

### 4.1 Dependency (from §2)
Offloading is the goal, but avoid *brittle* dependence and skill erosion. **→** Reliable capture + optional fading/scaffolding; make the user's *systems* portable and visible so value survives beyond the app.

### 4.2 Surveillance & "creepiness" / privacy of an all-day agent **[Strong ethics concern]**
Continuous passive monitoring raises acute autonomy, privacy, and consent concerns; in the digital-phenotyping literature, **only ~14% of studies even addressed anonymization**, and continuous sensing is flagged as posing novel autonomy/privacy risks ([Passive sensing for mental-health monitoring: scoping review, *JMIR* 2025](https://www.jmir.org/2025/1/e77066); [Ethical dimensions of digital phenotyping, *J Technol Behav Sci* 2024](https://link.springer.com/article/10.1007/s41347-024-00423-9)). An always-watching agent can feel like a boss/parent surveilling you.
- **→ Design rule:** **Local-first / on-device processing** wherever possible; explicit, granular, revocable consent for any "follow-along" sensing; a always-visible "what I can see right now" indicator and a one-tap **pause/blackout**. Collect the minimum needed; never make monitoring a precondition of help.

### 4.3 Infantilizing tone **[Strong — self-determination theory]**
Assistive tech that over-directs undermines **autonomy, competence, and relatedness** — the three needs of Self-Determination Theory — and can feel patronizing, reducing rather than building capability ([autonomy-supportive design for people with disabilities; SDT](https://arxiv.org/pdf/2511.17648)). ADHD users in the Tether study explicitly disliked surveillance-like, patronizing, one-size-fits-all behavior ([arXiv 2509.01946](https://arxiv.org/abs/2509.01946)).
- **→ Design rule:** **Peer, not parent.** Collaborative "we"-framing, celebrate agency ("nice call"), offer choices rather than commands, and let the user tune or overrule everything. Support autonomy — the tool *suggests, never enforces.*

### 4.4 Triggering RSD / emotional harm (from §1.8)
Streaks, red overdue badges, "you failed," disappointed tones, and gamified shame can land as rejection and trigger disproportionate emotional pain, driving avoidance of the tool itself.
- **→ Design rule:** No shame mechanics. No broken-streak guilt. Missed tasks are re-offered neutrally ("want to move this to tomorrow?"). Every string passes an "would this hurt at a vulnerable moment?" check.

### 4.5 Over-notification **[Strong — and it backfires functionally]**
Aggressive/rigid notifications disrupt flow, feel like nagging, and — per §3.5 — *don't even improve outcomes.* Tether's users wanted **soft, dismissible, brief, scannable, opt-in** prompts, self-set "attention windows," and transparency about *why* a suggestion appears ([arXiv 2509.01946](https://arxiv.org/abs/2509.01946)).
- **→ Design rule:** **Consent-first, low-volume, adaptive.** Every nudge is easily snoozed/dismissed with zero friction; frequency adapts down when ignored; respect user-defined focus/quiet windows; explain the "why" on demand. Silence is a valid, respected state.

### 4.6 What respectful design looks like (synthesis)
A **co-regulatory peer** that: externalizes cognition reliably; supports autonomy and choice; uses warm, non-judgmental, RSD-safe language; nudges gently, contextually, and rarely; keeps data private and local with visible controls; celebrates progress without manufacturing shame; and always leaves the human in charge. In one line from the design literature: *"support autonomy, not automation… a co-regulatory peer, not a taskmaster."*

---

## 5. Ranked Feature-Priority Table (for a 1-Day Hackathon Build)

Ranked by **impact ÷ effort**. Effort assumes an LLM agent + simple UI; "S" = a few hours, "M" = most of a day, "L" = >1 day. Top ~6 are the recommended MVP.

| # | Feature | Deficit(s) addressed | Evidence strength | Impact | Effort | Why it's a hackathon win |
|---|---------|----------------------|-------------------|--------|--------|--------------------------|
| 1 | **Frictionless thought/task capture** (one keystroke or voice → auto-filed, "handled" confirmation) | Working memory, prospective memory, intrusive thoughts/Zeigarnik | Strong | ★★★★★ | **S** | The literal "externalize working memory" thesis; trivial to build (input box + LLM parse); closes open loops instantly |
| 2 | **One-tap task auto-decomposition** (task → ≤15-min steps, tiny first step, shown one at a time) | Task initiation, Wall of Awful, working memory | Strong | ★★★★★ | **S** | Pure LLM prompt; directly lowers activation energy; visible dopamine loop per check-off |
| 3 | **If-then implementation-intention builder** (cue-bound plan, rehearsed once, fires on cue) | Task initiation, prospective memory, inhibition | **Strongest (d≈0.65, ADHD-specific RCTs)** | ★★★★★ | **S–M** | Best evidence-to-effort ratio in the entire brief |
| 4 | **Externalized "current context" panel + interruption re-entry** ("here's exactly where you were") | Working memory, task-switching cost | Strong | ★★★★☆ | **M** | Kills the biggest hidden cost (switch/re-entry); high felt value in a demo |
| 5 | **Ambient visual timer / focus sprint** (visible countdown, adjustable interval, gentle breaks) | Time blindness, task initiation | Moderate | ★★★★☆ | **S–M** | Simple to build; makes time *visible*; pairs with #6 |
| 6 | **"Work with me" body-doubling presence mode** (ambient co-worker, start/stop ritual, soft pings) | Task initiation, focus, emotional activation | Emerging (AI-double evidence exists) | ★★★★☆ | **S–M** | Demos beautifully; VR study shows an *AI* double works; cheap to prototype |
| 7 | **RSD-safe / co-regulating tone layer** (system-prompt tone rules; neutral re-offer of missed tasks; no shame) | Emotional dysregulation, RSD, Wall of Awful | Strong (as a design constraint) | ★★★★☆ | **S** | Just prompt engineering, but it's the difference between "helpful" and "harmful"; apply to *every* feature |
| 8 | **Context-aware / staged nudges** (event-triggered + 24h/2h/15min horizons; snooze/dismiss; adapt down) | Prospective memory, time blindness, initiation | Strong (JITAI + NICE); avoids the "dumb SMS" failure | ★★★★☆ | **M** | Higher effort (needs triggers/state), but this is what makes reminders actually work |
| 9 | **Event/context-based reminder conversion** (turn "at 3pm" into "when you open your laptop") | Prospective memory (exploits spared event-based channel) | Moderate–Strong | ★★★☆☆ | **M–L** | Clever and well-grounded, but needs sensing/integrations — stretch goal |
| 10 | **Estimate-vs-actual time calibration** (guess duration → log actuals → recalibrate) | Time blindness | Moderate | ★★★☆☆ | **M** | Nice-to-have; compounding value over time, less demo-able in one day |
| 11 | **Opt-in gentle accountability check-ins** | Task initiation, follow-through, emotional regulation | Moderate (coaching/CHADD) | ★★★☆☆ | **S** | Easy add-on to #8; must stay consented + warm |

**Recommended 1-day MVP:** **#1 + #2 + #3**, wrapped in the **#7 tone layer**, with **#5/#6** as the demo centerpiece. That combination is (a) buildable in a day, (b) resting on the strongest evidence (offloading ~45%→5%; implementation intentions d≈0.65; decomposition/activation-energy), and (c) demonstrably differentiated from a generic to-do app because it *starts tasks with the user* rather than just listing them.

---

### Evidence-confidence summary (read before over-claiming in the pitch)
- **Rock-solid:** working-memory deficit, time-perception deficit, emotional dysregulation as core, cognitive offloading benefit, implementation intentions.
- **Solid mechanism, thinner direct RCTs:** Pomodoro-for-ADHD, task-decomposition (clinical consensus, few controlled trials), coaching/accountability (strongest in students).
- **Emerging / clinical constructs (use as framing, don't over-state as settled science):** Wall of Awful, RSD (explicitly *not* a formal diagnosis), body doubling (mostly anecdotal, one supportive VR study).
- **Key honest counter-finding to design around:** *generic* reminders don't move outcomes (Nordby 2022) — the value is entirely in **context-aware, receptivity-sensitive, gentle** delivery.
