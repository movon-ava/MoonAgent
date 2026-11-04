"""Registry of target environments this agent created.

CTF² lets an agent hold only a couple of environments at a time, so a leaked
environment blocks every later container challenge (HTTP 409
``agent_environment_limit``). We therefore record each env we start, and on
startup (and after a crash) ``reconcile`` closes anything we no longer need.

The registry is intentionally "ours only": we never delete an environment we
did not register, because another tool may own it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "logs" / "target-envs.json"


def _read() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write(data: dict[str, dict[str, Any]]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STORE)


def register(
    challenge: str,
    *,
    ground_id: str = "",
    challenge_id: str = "",
    access_url: str = "",
) -> None:
    name = str(challenge or "").strip()
    if not name:
        return
    data = _read()
    data[name] = {
        "ground_id": ground_id,
        "challenge_id": challenge_id,
        "access_url": access_url,
        "created_at": time.time(),
    }
    _write(data)


def unregister(challenge: str) -> None:
    data = _read()
    if data.pop(str(challenge or "").strip(), None) is not None:
        _write(data)


def owned() -> dict[str, dict[str, Any]]:
    return _read()


def get(challenge: str) -> dict[str, Any] | None:
    return _read().get(str(challenge or "").strip())


def clear() -> int:
    data = _read()
    _write({})
    return len(data)
