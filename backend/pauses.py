"""Permanently paused challenges.

The platform answers ``40409`` on the answer endpoint when a challenge has run
out of submission attempts. That is not transient — retrying only wastes time
(and, with several models, tokens), so the exercise is parked in
``logs/pauses.json`` forever and filtered out of every later round.

Failure to *build* an environment also returns ``40409``, but that one means
"capacity is full right now", so callers must not pause on it (see
``Ctf2Client.ensure_env``).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "logs" / "pauses.json"


def _read() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - a corrupt pause file must not break rounds
        return {}


def _write(data: dict[str, dict[str, Any]]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STORE)


def pause(challenge: str, reason: str = "") -> None:
    name = str(challenge or "").strip()
    if not name:
        return
    data = _read()
    data[name] = {"reason": reason, "paused_at": time.time()}
    _write(data)


def is_paused(challenge: str) -> bool:
    return str(challenge or "").strip() in _read()


def paused_names() -> set[str]:
    return set(_read())


def unpause(challenge: str) -> bool:
    data = _read()
    if data.pop(str(challenge or "").strip(), None) is None:
        return False
    _write(data)
    return True


def clear() -> int:
    data = _read()
    _write({})
    return len(data)


def view() -> list[dict[str, Any]]:
    return [{"challenge": k, **v} for k, v in sorted(_read().items())]
