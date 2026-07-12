"""registry_io — the single, concurrency-safe writer for agents.json + ports.

The old path was unsafe at any concurrency: build_agent did a lock-free
read-modify-write of agents.json (last-writer-wins silently drops an entry) and
a connect-scan for a free port that never reserves it (two builds pick the same
port). This module makes the whole allocate-and-register step one critical
section:

  with_registry(mutator)   — take an exclusive lock, read the registry, let the
                             mutator add its entry (allocating ports against the
                             live registry so siblings can't collide), then write
                             it back atomically (temp file + os.replace).

Ports: brains need one literal port each (Hermes is one-gateway-per-profile).
We allocate from a wide dedicated block, bind()-verifying each candidate and
skipping anything already claimed by a registry entry. Replicas draw from their
own band so autoscaling can't exhaust the base range.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

from net_agents.atomicio import atomic_write, locked

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "agents.json"
LOCK = ROOT / "agents.lock"

# Dedicated, wide, non-overlapping port blocks (half-open [lo, hi)).
BRAIN_RANGE = (8700, 9200)      # 500 brain gateways
AGENT_RANGE = (9200, 9700)      # 500 forwarder services
REPLICA_BRAIN_RANGE = (9700, 9850)   # replica brains
REPLICA_AGENT_RANGE = (9850, 10000)  # replica services


class RegistryUnreadable(Exception):
    """agents.json exists but could not be parsed — refuse to overwrite it."""


def read() -> dict:
    """Return the registry. An ABSENT file is an empty registry; an UNREADABLE
    (corrupt/truncated) file raises, so with_registry never blanks a populated
    roster by writing back {} on top of a transient read failure."""
    if not REGISTRY.exists():
        return {}
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception as e:
        raise RegistryUnreadable(f"agents.json unreadable: {e}")


def read_lenient() -> dict:
    """Read-only best-effort view (returns {} on any error). For callers that
    only list and must never raise."""
    try:
        return read()
    except RegistryUnreadable:
        return {}


def _write(reg: dict) -> None:
    atomic_write(REGISTRY, json.dumps(reg, indent=2, ensure_ascii=False))


def _port_free(port: int) -> bool:
    """True if the OS will let us bind this port right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _claimed_ports(reg: dict) -> set[int]:
    claimed: set[int] = set()
    for v in reg.values():
        if isinstance(v, dict):
            for k in ("brain_port", "agent_port"):
                p = v.get(k)
                if isinstance(p, int):
                    claimed.add(p)
    return claimed


def allocate_port(reg: dict, rng: tuple[int, int], extra_taken: set[int]) -> int:
    """First port in `rng` that is free at the OS AND not claimed by any registry
    entry or already-picked sibling in this same allocation."""
    lo, hi = rng
    taken = _claimed_ports(reg) | extra_taken
    for p in range(lo, hi):
        if p in taken:
            continue
        if _port_free(p):
            return p
    raise RuntimeError(f"no free port in {lo}-{hi}")


def with_registry(mutator):
    """Run `mutator(reg)` under the exclusive registry lock and persist the result
    atomically. `mutator` receives the current registry dict, mutates it in place
    (allocating ports via allocate_port against that same dict), and returns any
    value the caller wants back. Serialises every writer, so concurrent builds
    never drop each other's entry or double-allocate a port."""
    with locked(LOCK):
        reg = read()
        result = mutator(reg)
        _write(reg)
        return result
