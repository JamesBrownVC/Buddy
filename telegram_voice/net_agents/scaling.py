"""scaling — the PURE autoscaling decision core (no I/O, no processes).

Given the current load on an agent's pool and a few timestamps, decide whether to
scale up (spawn a replica), scale down (drain one), or hold. Keeping this a pure
function is what makes the risky replica layer testable: the real replica_manager
consults decide() and only it touches processes.

The policy is deliberately hysteretic to avoid flapping given Hermes' ~90-120s
cold start:
  * scale UP when every ready instance is saturated AND we've been saturated for
    longer than a debounce (so a momentary spike doesn't spawn), up to max.
  * scale DOWN only after an instance has been idle for a long cooldown that is
    much larger than the spawn cost, and never below min (1 = the primary).
  * warming instances never count as ready (they can't serve yet).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Instance:
    id: str
    inflight: int = 0
    warming: bool = True            # True until warmup_s after spawn
    idle_since: int = 0             # ts it last went to 0 inflight (0 = never)
    spawned_at: int = 0


@dataclass
class AutoscaleConfig:
    per_instance_concurrency: int = 4
    min_instances: int = 1
    max_instances: int = 3
    warmup_s: int = 120            # exclude from LB until this after spawn
    scale_down_idle_s: int = 300   # drain an instance only after this idle
    saturated_debounce_s: int = 5  # must be saturated this long before scaling up
    action_cooldown_s: int = 30    # min gap between scale actions


@dataclass
class PoolState:
    instances: list[Instance] = field(default_factory=list)
    saturated_since: int = 0        # ts the pool first became fully saturated
    last_action_at: int = 0


def ready(instances: list[Instance], now: int, cfg: AutoscaleConfig) -> list[Instance]:
    """Instances that can serve now (done warming)."""
    return [i for i in instances if not i.warming and (now - i.spawned_at) >= 0]


def is_saturated(instances: list[Instance], cfg: AutoscaleConfig, now: int) -> bool:
    r = ready(instances, now, cfg)
    if not r:
        return True                 # nothing ready => treat as saturated (spawn)
    return all(i.inflight >= cfg.per_instance_concurrency for i in r)


def least_connections(instances: list[Instance], now: int,
                      cfg: AutoscaleConfig) -> Instance | None:
    """Pick the ready instance with the fewest in-flight requests."""
    r = [i for i in ready(instances, now, cfg)
         if i.inflight < cfg.per_instance_concurrency]
    return min(r, key=lambda i: i.inflight) if r else None


def decide(state: PoolState, cfg: AutoscaleConfig, now: int) -> dict:
    """Return {action: 'up'|'down'|'hold', reason, target?}.
    Pure: callers apply the action; this never mutates or spawns."""
    insts = state.instances
    n = len(insts)

    # respect a cooldown between actions so we never thrash
    if now - state.last_action_at < cfg.action_cooldown_s:
        return {"action": "hold", "reason": "cooldown"}

    # scale up: saturated (debounced) and below max
    if is_saturated(insts, cfg, now) and n < cfg.max_instances:
        if state.saturated_since and (now - state.saturated_since) >= cfg.saturated_debounce_s:
            return {"action": "up", "reason": "saturated"}
        return {"action": "hold", "reason": "saturation-debounce"}

    # scale down: an idle, non-primary instance past the cooldown
    if n > cfg.min_instances:
        for inst in insts:
            if inst.inflight == 0 and inst.idle_since and \
                    (now - inst.idle_since) >= cfg.scale_down_idle_s:
                return {"action": "down", "reason": "idle", "target": inst.id}

    return {"action": "hold", "reason": "steady"}
