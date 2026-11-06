"""Durable run snapshots for crash recovery.

A round can be interrupted by a crashed dashboard, a closed terminal, or a
reboot. Without a snapshot the only surviving trace is ``logs/round-history.json``
(which challenges were *attempted*), so the next run re-solves everything from
scratch — and re-pays for it.

Every round writes ``logs/runs/<run_id>/state.json``:

    {
      "run_id": "20261106-140013",
      "created_at": 1793…,
      "finished": false,
      "platform": "ctfplus",
      "round_size": 6,
      "model_specs": [...],
      "challenges": {
         "<name>": {"status": "running|solved|failed|timeout|skipped|already_solved",
                    "flag": null, "cost_usd": 0.0, "steps": 0,
                    "trace": "logs/trace-….jsonl", "updated_at": 1793…}
      }
    }

``latest_open()`` returns the newest unfinished run, which is what ``--resume``
and the dashboard's 「继续上次」 button use.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "logs" / "runs"

TERMINAL = {"solved", "skipped", "already_solved", "failed", "timeout"}


def _path(run_id: str) -> Path:
    return RUNS_DIR / run_id / "state.json"


def new_run(platform: str, round_size: int, model_specs: list[str]) -> str:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    state = {
        "run_id": run_id,
        "created_at": time.time(),
        "finished": False,
        "platform": platform,
        "round_size": int(round_size or 0),
        "model_specs": list(model_specs or []),
        "challenges": {},
    }
    save(run_id, state)
    return run_id


def save(run_id: str, state: dict[str, Any]) -> None:
    path = _path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.debug("suppressed exception", exc_info=True)


def load(run_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(_path(run_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def update_challenge(run_id: str, name: str, **fields: Any) -> None:
    state = load(run_id) or {}
    if not state:
        return
    entry = state.setdefault("challenges", {}).setdefault(name, {})
    entry.update(fields)
    entry["updated_at"] = time.time()
    save(run_id, state)


def finish(run_id: str) -> None:
    state = load(run_id) or {}
    if state:
        state["finished"] = True
        state["finished_at"] = time.time()
        save(run_id, state)


def list_runs(limit: int = 10) -> list[dict[str, Any]]:
    if not RUNS_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(RUNS_DIR.glob("*/state.json"), reverse=True)[:limit]:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ch = state.get("challenges") or {}
        state["total"] = len(ch)
        state["solved"] = sum(1 for c in ch.values() if c.get("status") == "solved")
        out.append(state)
    return out


def latest_open() -> dict[str, Any] | None:
    for state in list_runs(50):
        if not state.get("finished"):
            return state
    return None


def unfinished(state: dict[str, Any]) -> list[str]:
    return [
        name
        for name, c in (state.get("challenges") or {}).items()
        if str(c.get("status") or "") not in TERMINAL
    ]
