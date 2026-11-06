"""Per-challenge long-term notes.

A challenge often gets more than one solver: an extra round, a re-spawn after a
timeout, a fresh container after the platform target died. Each of those used to
start from a blank context and re-derive facts the previous run already knew
(service protocol, offsets, dead ends, rejected flags).

This module keeps a small append-only notebook per challenge under
``logs/memory/<slug>.md``; the solver reads a digest in its prompt and can add to
it with the ``remember`` tool. Notes are local-only and never uploaded.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
MEM_DIR = ROOT / "logs" / "memory"

MAX_FILE_CHARS = 12_000  # keep the newest part when the notebook grows
MAX_NOTE_CHARS = 900
DIGEST_CHARS = 2_200


def _slug(challenge: str) -> str:
    slug = re.sub(r"[^\w.\-]+", "_", (challenge or "").strip(), flags=re.UNICODE)
    return slug.strip("_")[:80] or "challenge"


def path_for(challenge: str) -> Path:
    return MEM_DIR / f"{_slug(challenge)}.md"


def note(challenge: str, kind: str, text: str) -> str:
    """Append one line to the challenge notebook; returns the file path."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return str(path_for(challenge))
    if len(text) > MAX_NOTE_CHARS:
        text = text[: MAX_NOTE_CHARS - 1] + "…"
    kind = re.sub(r"[^\w-]+", "", str(kind or "note"))[:16] or "note"
    path = path_for(challenge)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%m-%d %H:%M")
    line = f"- [{stamp} {kind}] {text}\n"
    try:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        merged = old + line
        if len(merged) > MAX_FILE_CHARS:
            # Drop the oldest lines, keep a short header.
            kept = merged[-MAX_FILE_CHARS:]
            cut = kept.find("\n- [")
            if cut > 0:
                kept = kept[cut + 1 :]
            merged = kept
        path.write_text(merged, encoding="utf-8")
    except OSError:
        logger.debug("suppressed exception", exc_info=True)
    return str(path)


def digest(challenge: str, max_chars: int = DIGEST_CHARS) -> str:
    """Newest notes for the prompt, or "" when this challenge was never seen."""
    path = path_for(challenge)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not text:
        return ""
    if len(text) > max_chars:
        text = "…\n" + text[-max_chars:]
    return text


def clear(challenge: str) -> None:
    try:
        path_for(challenge).unlink()
    except OSError:
        logger.debug("suppressed exception", exc_info=True)
