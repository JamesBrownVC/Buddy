"""dispatcher — per-agent backpressure, load-balancing and payload management.

The hub used to run every /agents/ask through one shared threadpool, so a single
slow 120s brain could starve every other agent, the planner heartbeat and the
dashboard. The dispatcher fixes that with classic traffic-management pieces,
per agent:

  * a concurrency semaphore (at most N in-flight per agent),
  * a bounded queue with load-shedding (return "busy" instead of unbounded pileup),
  * a circuit breaker (after repeated failures, fail fast for a cooldown instead
    of hammering a dead brain),
  * payload truncation (cap relayed sub-replies so one huge browser dump doesn't
    blow up the caller's context).

It is opt-in (BUDDY_DISPATCHER=1) so the live hub path is unchanged until enabled;
the logic is fully unit-testable with a fake forward function.
"""
from __future__ import annotations

import asyncio
import os
import time

MAX_RELAY_BYTES = 8000              # cap on a relayed sub-reply
HOP_DEPTH_CAP = 4                   # router->orch->agent... hard ceiling


def truncate_payload(text: str, limit: int = MAX_RELAY_BYTES) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated {len(text) - limit} chars]"


class CircuitBreaker:
    """Open after `threshold` consecutive failures; half-open after `cooldown`."""

    def __init__(self, threshold: int = 5, cooldown: float = 30.0):
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at = 0.0
        self.probing = False            # a half-open probe is in flight

    def allow(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        if self.failures < self.threshold:
            return True
        # Open: allow exactly ONE probe per cooldown, not an unbounded burst.
        # Safe check-and-set: allow() has no await under single-threaded asyncio.
        if not self.probing and (now - self.opened_at) >= self.cooldown:
            self.probing = True
            return True
        return False

    def record(self, ok: bool, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.probing = False
        if ok:
            self.failures = 0
            self.opened_at = 0.0
        else:
            self.failures += 1
            if self.failures >= self.threshold:
                self.opened_at = now


class AgentPool:
    """Concurrency + queue + breaker for a single agent."""

    def __init__(self, concurrency: int = 4, queue_max: int = 8):
        self.sem = asyncio.Semaphore(concurrency)
        self.concurrency = concurrency
        self.queue_max = queue_max
        self.waiting = 0
        self.inflight = 0
        self.breaker = CircuitBreaker()


class Dispatcher:
    def __init__(self, concurrency: int = 4, queue_max: int = 8):
        self._pools: dict[str, AgentPool] = {}
        self.concurrency = concurrency
        self.queue_max = queue_max

    def pool(self, agent: str) -> AgentPool:
        p = self._pools.get(agent)
        if p is None:
            p = AgentPool(self.concurrency, self.queue_max)
            self._pools[agent] = p
        return p

    async def dispatch(self, agent: str, forward, *, depth: int = 0) -> dict:
        """Run `forward()` (an async callable returning a reply str) under the
        agent's pool. Returns {reply, shed?, tripped?, truncated?}."""
        if depth >= HOP_DEPTH_CAP:
            return {"reply": "hop-depth cap reached; request stopped.",
                    "shed": True}
        p = self.pool(agent)
        if not p.breaker.allow():
            return {"reply": f"{agent} is temporarily unavailable (circuit open).",
                    "shed": True}
        if p.waiting >= p.queue_max:
            p.breaker.probing = False   # give back a probe we won't actually run
            return {"reply": f"{agent} is busy, try again shortly.", "shed": True}

        p.waiting += 1
        try:
            async with p.sem:
                p.inflight += 1
                try:
                    reply = await forward()
                    p.breaker.record(True)
                    return {"reply": truncate_payload(reply)}
                except Exception as e:
                    p.breaker.record(False)
                    return {"reply": f"{agent} failed: {e}", "error": True}
                finally:
                    p.inflight -= 1
        finally:
            p.waiting -= 1              # always released, even on cancel/error


_singleton: Dispatcher | None = None


def enabled() -> bool:
    return os.getenv("BUDDY_DISPATCHER", "0").lower() in {"1", "true", "yes"}


def get() -> Dispatcher:
    global _singleton
    if _singleton is None:
        _singleton = Dispatcher(
            concurrency=int(os.getenv("BUDDY_AGENT_CONCURRENCY", "4")),
            queue_max=int(os.getenv("BUDDY_AGENT_QUEUE", "8")))
    return _singleton
