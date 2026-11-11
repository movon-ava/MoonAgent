"""On-demand skill catalogue.

A *skill* is a Markdown file under ``skills/<category>/<slug>.md`` with a small
YAML-ish frontmatter block::

    ---
    name: pwn/format-string
    description: 一句话说明这个技能解决什么问题
    when_to_use: 什么时候该加载它
    categories: [pwn]
    keywords: [fmtstr, %p, %n]
    ---
    正文（命令、脚本模板、常见坑）

Only the index (name + when_to_use) goes into the prompt; the solver pulls the
full body in with the ``use_skill`` tool when it actually needs it. That keeps
the prompt small while still giving the model deep, per-technique knowledge.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

MAX_BODY_CHARS = 8000
INDEX_CHARS = 1600

_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)
_LIST_RE = re.compile(r"^(?P<key>[A-Za-z_]+)\s*:\s*\[(?P<value>.*)\]\s*$")
_SCALAR_RE = re.compile(r"^(?P<key>[A-Za-z_]+)\s*:\s*(?P<value>.*)$")

_CACHE: tuple[float, list[Skill]] | None = None


@dataclass(frozen=True)
class Skill:
    """One catalogued technique."""

    name: str
    description: str
    when_to_use: str
    categories: tuple[str, ...]
    keywords: tuple[str, ...]
    body: str
    path: str


def _split_list(raw: str) -> tuple[str, ...]:
    items = [part.strip().strip("\"'") for part in raw.split(",")]
    return tuple(item for item in items if item)


def _parse(text: str, rel: str) -> Skill | None:
    match = _FRONT_RE.match(text)
    if not match:
        logger.debug("skill %s has no frontmatter - skipped", rel)
        return None
    fields: dict[str, str] = {}
    lists: dict[str, tuple[str, ...]] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        list_match = _LIST_RE.match(line)
        if list_match:
            lists[list_match.group("key")] = _split_list(list_match.group("value"))
            continue
        scalar_match = _SCALAR_RE.match(line)
        if scalar_match:
            fields[scalar_match.group("key")] = scalar_match.group("value").strip().strip("\"'")
    name = fields.get("name") or rel
    body = text[match.end():].strip()
    if not body:
        logger.debug("skill %s has an empty body - skipped", rel)
        return None
    return Skill(
        name=name,
        description=fields.get("description", ""),
        when_to_use=fields.get("when_to_use", "") or fields.get("description", ""),
        categories=lists.get("categories", ()),
        keywords=lists.get("keywords", ()),
        body=body[:MAX_BODY_CHARS],
        path=rel,
    )


def resolve_dir(value: str | Path | None = None) -> Path:
    """Map ``skills_dir`` from settings onto a real path (relative = repo root)."""
    if not value:
        return SKILLS_DIR
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path)


def catalog(directory: Path | str | None = None) -> list[Skill]:
    """Return every valid skill, sorted by name (cached on directory mtime)."""
    global _CACHE
    base = Path(directory) if directory else SKILLS_DIR
    try:
        stamp = base.stat().st_mtime
    except OSError:
        return []
    if _CACHE is not None and _CACHE[0] == stamp and directory is None:
        return list(_CACHE[1])
    found: list[Skill] = []
    for path in sorted(base.rglob("*.md")):
        try:
            skill = _parse(path.read_text(encoding="utf-8", errors="replace"), str(path.relative_to(base)))
        except OSError as exc:  # pragma: no cover - unreadable file
            logger.debug("cannot read skill %s: %s", path, exc)
            continue
        if skill is not None:
            found.append(skill)
    found.sort(key=lambda s: s.name)
    if directory is None:
        _CACHE = (stamp, found)
    return list(found)


def names(directory: Path | str | None = None) -> list[str]:
    return [skill.name for skill in catalog(directory)]


def body(name: str, directory: Path | str | None = None) -> str | None:
    """Full Markdown body of one skill, or None when unknown."""
    for skill in catalog(directory):
        if skill.name == name:
            return skill.body
    return None


def _tag_matches(category: str, tag: str) -> bool:
    """True when a challenge category and a skill tag are the same direction.

    The platform spells REVERSE as ``REVRESE`` and CTF² as ``CRYPTO``, so a
    prefix match is enough ("revrese".startswith("re"), "crypto".startswith("cr")).
    """
    category, tag = category.lower(), tag.lower()
    return bool(category) and bool(tag) and (
        category == tag or category.startswith(tag) or tag.startswith(category)
    )


def match(category: str = "", text: str = "", limit: int = 3, directory: Path | str | None = None) -> list[Skill]:
    """Rank skills for a challenge: same category first, then keyword hits."""
    category = (category or "").strip().lower()
    haystack = (text or "").lower()
    scored: list[tuple[int, str, Skill]] = []
    for skill in catalog(directory):
        score = 0
        if any(_tag_matches(category, tag) for tag in skill.categories):
            score += 10
        for keyword in skill.keywords:
            if keyword.lower() and keyword.lower() in haystack:
                score += 3
        if score:
            scored.append((-score, skill.name, skill))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored[:limit]]


def index_text(category: str = "", limit: int = INDEX_CHARS, directory: Path | str | None = None) -> str:
    """One line per skill for the prompt: ``- name — when to use``."""
    skills = catalog(directory)
    if not skills:
        return ""
    preferred = [s for s in skills if any(_tag_matches(category, tag) for tag in s.categories)]
    rest = [s for s in skills if s not in preferred]
    lines: list[str] = []
    used = 0
    for skill in [*preferred, *rest]:
        line = f"- `{skill.name}` — {skill.when_to_use}"
        if used + len(line) + 1 > limit and lines:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
