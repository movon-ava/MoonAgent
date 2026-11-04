"""Pacing for competition-platform API calls.

The DASCTF/CTF² APIs rate-limit aggressively: bursts of detail requests used to
come back as HTTP 429 and stall a whole round. Borrowed from the reference Go
agent, every platform request now waits for a global minimum interval since the
previous request *finished* (failed calls count too). The timestamp lives in a
small file next to an OS file lock, so two runners sharing this checkout also
pace each other.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOCK_FILE = LOG_DIR / ".platform-request.lock"
STATE_FILE = LOG_DIR / ".platform-request.state"

DEFAULT_INTERVAL = 0.8
_local_lock = asyncio.Lock()


def _lock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    except Exception:  # noqa: BLE001 - pacing must never break a solve
        pass


def _unlock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001
        pass


def _read_last() -> float:
    try:
        return float(STATE_FILE.read_text(encoding="utf-8").strip() or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _write_last(value: float) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(f"{value:.6f}", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


async def wait_turn(interval: float = DEFAULT_INTERVAL) -> None:
    """Block until ``interval`` seconds have passed since the last request."""
    interval = max(0.0, float(interval))
    if interval <= 0:
        return
    async with _local_lock:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fh = open(LOCK_FILE, "a+b")  # noqa: SIM115 - short-lived lock handle
        try:
            while True:
                _lock(fh)
                try:
                    last = _read_last()
                    now = time.time()
                    wait = last + interval - now
                    if wait <= 0:
                        _write_last(now)
                        return
                finally:
                    _unlock(fh)
                await asyncio.sleep(min(wait, 0.25))
        finally:
            fh.close()
