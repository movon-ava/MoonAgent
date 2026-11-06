"""Category checklists ("knowledge base") injected into solver prompts.

The reference audit pack (LTX-GOD/Pi-for-sec) has no CTF knowledge base — its
files are SRC audit roles — so these checklists are distilled from our own run
experience. Keeping them as plain Markdown means anyone can edit them without
touching code; ``knowledge/<category>.md`` is looked up by direction.
"""

from __future__ import annotations

import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "knowledge"

ALIASES = {
    "web": "web",
    "渗透": "web",
    "pwn": "pwn",
    "二进制": "pwn",
    "re": "re",
    "reverse": "re",
    "逆向": "re",
    "crypto": "crypto",
    "密码": "crypto",
    "misc": "misc",
    "杂项": "misc",
    "取证": "misc",
    "隐写": "misc",
}

logger = logging.getLogger(__name__)


def category_key(category: str) -> str:
    text = str(category or "").strip().lower()
    for alias, key in ALIASES.items():
        if alias in text:
            return key
    return "misc"


def digest(category: str, max_chars: int = 2600) -> str:
    """Return the checklist for ``category`` (empty when the file is missing)."""
    path = KB_DIR / f"{category_key(category)}.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n…"
    return text
