# Router — lightweight dispatcher

A deliberately non-Hermes utility. Given a request an agent can't handle (or a
"who should do this?"), it makes one fast model call to pick the single best
agent, forwards over the /ask contract, and returns the answer. One classify +
one hop — no Hermes runtime, no agent-loop. Agents lean on it instead of each
reasoning over the whole (growing) roster; it never routes back to the asker.
