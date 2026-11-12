"""Accumulated solving chains ("logic chains").

A *skill* answers "how do I do X".  A *chain* answers the harder question:
"in what order do I try things, and how do I know each step worked before
moving on".  A chain is a Markdown file under ``chains/<category>/<slug>.md``
with a frontmatter block::

    ---
    name: re/upx-garble-go
    description: 魔改 UPX + garble 的 Go 逆向
    when_to_use: 节区名异常、熵高、入口在最后一段、能看到 Go buildinfo
    categories: [re]
    keywords: [upx, garble, golang, pclntab]
    stages: [侦察, 识别壳, 脱壳, 验 OEP, 找 Go 元数据, 定位 main, 还原算法, 产出 flag]
    source: trace-RE6-deepseek-flash-20261107-131153.jsonl
    ---
    ## 1. 侦察
    动作：...
    判据：...
    失败分支：...

Only a compact index (name + stage skeleton) goes into the prompt; the solver
pulls the full body with ``use_chain`` when the signals match.  ``scripts/
chain_report.py`` shows what has been accumulated and how often each chain was
actually loaded.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from backend.skills import _tag_matches

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CHAINS_DIR = ROOT / "chains"

MAX_BODY_CHARS = 12_000
INDEX_CHARS = 1_200

_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)
_LIST_RE = re.compile(r"^(?P<key>[A-Za-z_]+)\s*:\s*\[(?P<value>.*)\]\s*$")
_SCALAR_RE = re.compile(r"^(?P<key>[A-Za-z_]+)\s*:\s*(?P<value>.*)$")

_CACHE: tuple[float, list[Chain]] | None = None


@dataclass(frozen=True)
class Chain:
    """One accumulated solving path."""

    name: str
    description: str
    when_to_use: str
    categories: tuple[str, ...]
    keywords: tuple[str, ...]
    stages: tuple[str, ...]
    source: str
    body: str
    path: str


def _split_list(raw: str) -> tuple[str, ...]:
    items = [part.strip().strip("\"'") for part in raw.split(",")]
    return tuple(item for item in items if item)


def _parse(text: str, rel: str) -> Chain | None:
    match = _FRONT_RE.match(text)
    if not match:
        logger.debug("chain %s has no frontmatter - skipped", rel)
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
            fields[scalar_match.group("key")] = (
                scalar_match.group("value").strip().strip("\"'")
            )
    body = text[match.end():].strip()
    if not body:
        logger.debug("chain %s has an empty body - skipped", rel)
        return None
    return Chain(
        name=fields.get("name") or rel,
        description=fields.get("description", ""),
        when_to_use=fields.get("when_to_use", "") or fields.get("description", ""),
        categories=lists.get("categories", ()),
        keywords=lists.get("keywords", ()),
        stages=lists.get("stages", ()),
        source=fields.get("source", ""),
        body=body[:MAX_BODY_CHARS],
        path=rel,
    )


def resolve_dir(value: str | Path | None = None) -> Path:
    """Map ``chains_dir`` from settings onto a real path (relative = repo root)."""
    if not value:
        return CHAINS_DIR
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path)


def catalog(directory: Path | str | None = None) -> list[Chain]:
    """Load every chain under ``directory`` (cached by directory mtime)."""
    global _CACHE
    root = resolve_dir(directory)
    if not root.is_dir():
        return []
    try:
        stamp = root.stat().st_mtime
    except OSError:
        return []
    if _CACHE is not None and abs(_CACHE[0] - stamp) < 1e-6:
        return list(_CACHE[1])
    found: list[Chain] = []
    for path in sorted(root.rglob("*.md")):
        rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        if any(part.startswith("_") for part in path.relative_to(root).parts):
            # _drafts/ holds machine-written skeletons that are not reviewed yet.
            continue
        try:
            chain = _parse(path.read_text(encoding="utf-8", errors="replace"), rel)
        except OSError as exc:
            logger.debug("cannot read chain %s: %s", rel, exc)
            continue
        if chain is not None:
            found.append(chain)
    _CACHE = (stamp, found)
    return list(found)


def names(directory: Path | str | None = None) -> tuple[str, ...]:
    return tuple(chain.name for chain in catalog(directory))


def body(name: str, directory: Path | str | None = None) -> str | None:
    """Return the full text of one chain (``None`` when it does not exist)."""
    for chain in catalog(directory):
        if chain.name == name:
            header = " | ".join(chain.stages)
            return f"# {chain.name}\n阶段：{header}\n\n{chain.body}"
    return None


def match(
    category: str,
    text: str,
    limit: int = 2,
    directory: Path | str | None = None,
) -> list[Chain]:
    """Rank chains for a challenge: same direction first, then keyword hits."""
    haystack = f" {text.lower()} "
    scored: list[tuple[int, str, Chain]] = []
    for chain in catalog(directory):
        score = 0
        if any(_tag_matches(category, tag) for tag in chain.categories):
            score += 10
        for keyword in chain.keywords:
            needle = keyword.lower()
            if needle and needle in haystack:
                score += 3
        if score:
            scored.append((score, chain.name, chain))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]


def _line(chain: Chain) -> str:
    stages = " → ".join(chain.stages) if chain.stages else "(未写阶段)"
    hint = chain.when_to_use.strip()
    if len(hint) > 60:
        hint = hint[:57] + "…"
    return f"- `{chain.name}`：{stages}（进入信号：{hint}）"


def index_text(
    category: str,
    limit: int = INDEX_CHARS,
    directory: Path | str | None = None,
) -> str:
    """Compact stage skeleton for the prompt (same direction first)."""
    chains = catalog(directory)
    if not chains:
        return ""
    ordered = sorted(
        chains,
        key=lambda chain: (
            0 if any(_tag_matches(category, tag) for tag in chain.categories) else 1,
            chain.name,
        ),
    )
    lines: list[str] = []
    used = 0
    for chain in ordered:
        line = _line(chain)
        if used + len(line) + 1 > limit:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
