"""Operator hints typed at the terminal while agents are running.

The CLI starts a daemon thread that reads lines from stdin. Every non-empty
line is queued; the solver's tool wrapper drains the queue after each tool call
and appends the hint to the tool result, so the model sees it on its very next
step — no restart, no separate console.

This is the terminal equivalent of Codex's bottom input box: run a round, then
just type a hint and press Enter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)

_console = Console()

HINT_DIR = Path("logs") / "hints"

# One queue per challenge plus a broadcast queue for terminal hints, so a hint
# addressed to challenge A can never be consumed by the solver of challenge B
# (the coordinator runs several swarms in the same process).
_queues: dict[str, asyncio.Queue[str]] = {}
BROADCAST = "_all"
_thread: threading.Thread | None = None
_started = False
_file_watchers: dict[str, threading.Thread] = {}


def _ensure_queue(key: str = BROADCAST) -> asyncio.Queue[str]:
    queue = _queues.get(key)
    if queue is None:
        queue = asyncio.Queue()
        _queues[key] = queue
    return queue


def hint_file_for(challenge: str) -> Path:
    """File the web UI writes to for one challenge (``PWN`` → logs/hints/PWN.jsonl)."""
    safe = re.sub(r"[^\w.\-]+", "_", (challenge or "").strip()) or "all"
    return HINT_DIR / f"{safe}.jsonl"


def append_hint(challenge: str, text: str) -> Path:
    """Append a hint for ``challenge`` (used by the web UI / scripts)."""
    path = hint_file_for(challenge)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "text": text}, ensure_ascii=False) + "\n")
    return path


_file_stops: dict[str, threading.Event] = {}


def stop_file_hint_watcher(challenge: str) -> None:
    """Stop the per-challenge watcher (solver finished; do not leak threads)."""
    stop = _file_stops.pop(challenge, None)
    if stop is not None:
        stop.set()
    _file_watchers.pop(challenge, None)


def start_file_hint_watcher(challenge: str) -> None:
    """Watch ``logs/hints/<challenge>.jsonl`` and queue new lines.

    Lets a separate process (the web UI) inject hints while a round is running.
    """
    if not challenge or challenge in _file_watchers:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    path = hint_file_for(challenge)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    try:
        offset = path.stat().st_size
    except OSError:
        offset = 0

    queue = _ensure_queue(challenge)
    stop = threading.Event()
    _file_stops[challenge] = stop

    def _watch() -> None:
        nonlocal offset
        while not stop.is_set():
            time.sleep(1.0)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size < offset:  # truncated
                offset = 0
            if size == offset:
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    f.seek(offset)
                    chunk = f.read()
                    offset = f.tell()
            except OSError:
                continue
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    text = str(json.loads(line).get("text") or "").strip()
                except Exception:
                    text = line
                if not text:
                    continue
                loop.call_soon_threadsafe(queue.put_nowait, text)
                try:
                    _console.print(
                        f"[yellow]↵ 网页提示已排队[/yellow] [dim]{text}[/dim]",
                        highlight=False,
                        soft_wrap=True,
                    )
                except Exception:
                    pass

    thread = threading.Thread(target=_watch, name=f"ctf-hint-file-{challenge}", daemon=True)
    thread.start()
    _file_watchers[challenge] = thread
    logger.info("Hint file watcher started: %s", path)


def start_hint_listener(stream: Any | None = None) -> None:
    """Start reading hints from stdin in a daemon thread (idempotent)."""
    global _thread, _started

    if _started:
        return
    source = stream if stream is not None else sys.stdin
    if source is None:
        return
    try:
        source.fileno()
    except (AttributeError, OSError, ValueError):
        return  # not a real terminal / pipe we can read from

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    _started = True
    queue = _ensure_queue(BROADCAST)

    def _reader() -> None:
        while True:
            try:
                line = source.readline()
            except Exception:
                return
            if not line:
                return
            text = line.strip()
            if not text:
                continue
            loop.call_soon_threadsafe(queue.put_nowait, text)
            try:
                _console.print(
                    f"[yellow]↵ 提示已排队[/yellow] [dim]{text}[/dim]",
                    highlight=False,
                    soft_wrap=True,
                )
            except Exception:
                pass

    _thread = threading.Thread(target=_reader, name="ctf-hint-input", daemon=True)
    _thread.start()
    logger.info("Hint input listener started (type a line + Enter to inject)")


def hints_pending(challenge: str | None = None) -> int:
    total = 0
    for key in (challenge, BROADCAST):
        queue = _queues.get(key or "")
        if queue is not None:
            total += queue.qsize()
    return total


async def pop_hints(challenge: str | None = None) -> list[str]:
    """Drain hints addressed to ``challenge`` plus broadcast (terminal) hints."""
    out: list[str] = []
    for key in (challenge, BROADCAST):
        queue = _queues.get(key or "")
        if queue is None:
            continue
        while not queue.empty():
            out.append(queue.get_nowait())
    return out
