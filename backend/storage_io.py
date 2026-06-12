"""Atomic, lock-guarded JSON persistence helpers.

The stores previously did read-all -> mutate-in-memory -> write_text (truncate +
rewrite) with no lock. FastAPI serves sync handlers from a threadpool, so two
concurrent approve/execute requests could both read then both write, silently
dropping one mutation (lost update); and a crash mid-write left a truncated file
that readers swallowed as an empty list. This module centralizes:

- read_json: tolerant read that logs (rather than hides) corruption.
- write_json_atomic: temp-file + os.replace, which is atomic on the same filesystem.
- update_json: a lock-guarded read-modify-write so concurrent mutations serialize.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_tmp_counter = itertools.count()


def _lock_for(path: Path) -> threading.Lock:
    key = str(Path(path).resolve())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def read_json(path: Path, default: Any) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        # Surface corruption in logs instead of silently returning "empty".
        logger.error("Corrupt or unreadable JSON store at %s: %s", p, error)
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp name per writer (pid + thread + counter) so concurrent writers to
    # different paths never collide on the temp file.
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.{next(_tmp_counter)}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    # os.replace is atomic, but on Windows it can transiently fail with PermissionError
    # if an AV scanner / indexer is briefly holding the destination — retry a few times.
    last_error: OSError | None = None
    for attempt in range(10):
        try:
            os.replace(tmp, p)
            return
        except PermissionError as error:  # pragma: no cover - timing dependent
            last_error = error
            time.sleep(0.01 * (attempt + 1))
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    raise last_error if last_error else OSError(f"Failed to write {p}")


def update_json(path: Path, mutator: Callable[[Any], Any], *, default: Any) -> Any:
    """Lock-guarded read-modify-write.

    `mutator` receives the loaded data, mutates it in place, and returns a value to
    hand back to the caller (e.g. the affected row). The (mutated) data is then written
    atomically. The whole sequence holds a per-path lock so concurrent callers can't
    lose each other's updates.
    """
    with _lock_for(path):
        data = read_json(path, default)
        result = mutator(data)
        write_json_atomic(path, data)
        return result
