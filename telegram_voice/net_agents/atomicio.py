"""atomicio — crash-safe file primitives shared across the mesh.

Three guarantees the mesh needs but did not have:
  * locked(path)         — an exclusive advisory lock (single-writer critical
                           section), so concurrent builds/replicas serialise.
  * atomic_write(path)   — write to a same-dir temp file then os.replace(), so a
                           reader never sees a half-written file and a crash
                           mid-write cannot corrupt the original.
  * atomic_append(path)  — a lock-guarded append, so two writers never interleave
                           bytes inside a single JSONL line.

POSIX only for the lock (fcntl); on Windows the lock degrades to a no-op (the
mesh's concurrent paths are macOS/Linux — see start_all_mac.py). Nothing here
ever raises to the caller for a lock/IO hiccup: durability is best-effort and
must never take down a request path.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

try:                                    # POSIX advisory locks
    import fcntl
    _HAVE_FCNTL = True
except Exception:                       # pragma: no cover - Windows
    _HAVE_FCNTL = False


@contextlib.contextmanager
def locked(lock_path: str | os.PathLike):
    """Hold an exclusive advisory lock for the duration of the block.

    The lock is keyed on a sidecar file (e.g. agents.lock) so it is independent
    of the data file's own open/replace churn — os.replace() swaps the data
    file's inode, which would drop a lock held on the data file itself.
    """
    lock_path = Path(lock_path)
    if not _HAVE_FCNTL:
        yield
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def atomic_write(path: str | os.PathLike, data: str) -> None:
    """Replace `path`'s contents atomically (same-dir temp + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)           # atomic on the same filesystem
        # fsync the directory so the rename itself survives power loss
        with contextlib.suppress(Exception):
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except Exception:
        with contextlib.suppress(Exception):
            os.unlink(tmp)
        raise


def atomic_append(path: str | os.PathLike, line: str,
                  lock_path: str | os.PathLike | None = None) -> None:
    """Append one line under an exclusive lock so writers never interleave.

    `line` is written with exactly one trailing newline. Best-effort: a failure
    to append is swallowed (callers use this for logs/memory, never control flow).
    """
    path = Path(path)
    lock_path = Path(lock_path) if lock_path else path.with_suffix(path.suffix + ".lock")
    payload = line if line.endswith("\n") else line + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked(lock_path):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(payload)
    except Exception:
        pass
