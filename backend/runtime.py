"""Tiny runtime control channel shared by the CLI round runner and the web UI.

The web dashboard writes ``logs/runtime.json`` while a round is running; the
round runner polls it every couple of seconds so things like the concurrency
limit can be changed without stopping/restarting the run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RUNTIME_FILE = Path("logs") / "runtime.json"


def read_runtime() -> dict[str, Any]:
    try:
        data = json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_runtime(**values: Any) -> dict[str, Any]:
    """Merge ``values`` into the runtime file (best effort)."""
    data = read_runtime()
    data.update(values)
    try:
        RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - disk problems are rare
        logger.warning("cannot write %s: %s", RUNTIME_FILE, exc)
    return data


def reset_runtime() -> None:
    try:
        RUNTIME_FILE.unlink()
    except OSError:
        pass


def get_concurrency() -> int | None:
    """Concurrency requested by the dashboard, or ``None`` when unset."""
    value = read_runtime().get("max_concurrent")
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def set_concurrency(value: int) -> int:
    number = max(1, int(value))
    write_runtime(max_concurrent=number)
    return number


class SolverSkipped(Exception):
    """Raised inside a solver when the operator asks to skip its challenge."""


def request_skip(challenge: str) -> list[str]:
    """Queue "skip this challenge" for the running solver (web UI button)."""
    name = str(challenge or "").strip()
    if not name:
        return []
    data = read_runtime()
    skips = [str(x) for x in (data.get("skip") or []) if str(x).strip()]
    if name not in skips:
        skips.append(name)
    write_runtime(skip=skips)
    return skips


def pending_skips() -> list[str]:
    return [str(x) for x in (read_runtime().get("skip") or []) if str(x).strip()]


def consume_skip(challenge: str) -> bool:
    """Return True (and clear the flag) when this challenge should stop now."""
    name = str(challenge or "").strip()
    if not name:
        return False
    data = read_runtime()
    skips = [str(x) for x in (data.get("skip") or []) if str(x).strip()]
    if name not in skips:
        return False
    write_runtime(skip=[s for s in skips if s != name])
    return True
