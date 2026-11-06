"""Challenge selection policies for round ("drill") mode.

Two complaints drove this module:

* "every batch should switch direction" — ``rotate_chunks`` walks categories in
  order (misc -> re -> crypto -> ...) and hands out one batch at a time, so a
  round solves five MISC challenges, then five RE ones, and so on;
* "the difficulty mix is broken" — CTF² scores are all 1 point, so score-based
  ordering tells us nothing. ``balance_by_tier`` round-robins across the
  difficulty tiers instead, which guarantees that every batch of four or more
  contains a hard/medium/easy/intro challenge whenever the pool has them.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

TIERS = ("困难", "中等", "简单", "入门")
_UNKNOWN_TIER = ""


def tier_of(challenge: dict[str, Any]) -> str:
    tier = str(challenge.get("difficulty") or "").strip()
    if tier in TIERS:
        return tier
    # Platform stubs often carry the difficulty as a tag instead.
    for tag in challenge.get("tags") or ():
        text = str(tag or "").strip()
        if text in TIERS:
            return text
    return _UNKNOWN_TIER


def balance_by_tier(challenges: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Interleave challenges across tiers (hardest tier first, round-robin).

    Within a tier the original order is kept, so a caller that sorted by score
    or by "hard first" keeps that intent; the tiers just stop one another from
    monopolising the batch.
    """
    buckets: dict[str, list[dict[str, Any]]] = {t: [] for t in TIERS}
    others: list[dict[str, Any]] = []
    for ch in challenges:
        tier = tier_of(ch)
        if tier:
            buckets[tier].append(ch)
        else:
            others.append(ch)
    out: list[dict[str, Any]] = []
    queues = [buckets[t] for t in TIERS]
    while any(queues):
        for queue in queues:
            if queue:
                out.append(queue.pop(0))
    out.extend(others)
    return out


def rotate_chunks(
    challenges: Iterable[dict[str, Any]],
    batch: int,
    category_order: Iterable[str] = (),
    include_solved: bool = False,
) -> list[list[dict[str, Any]]]:
    """Split ``challenges`` into per-category batches of at most ``batch``.

    ``category_order`` fixes which direction comes first (e.g. ``misc`` before
    ``re``); categories not listed are appended in first-seen order. Each batch
    is tier-balanced so a direction is not all easy or all hard.
    """
    batch = max(1, int(batch))
    groups: dict[str, list[dict[str, Any]]] = {}
    for ch in challenges:
        if not include_solved and ch.get("solved"):
            continue
        cat = str(ch.get("category") or "").strip().lower() or "misc"
        groups.setdefault(cat, []).append(ch)

    order: list[str] = []
    for cat in category_order:
        key = str(cat or "").strip().lower()
        if key and key in groups and key not in order:
            order.append(key)
    order.extend(cat for cat in groups if cat not in order)

    per_category: list[list[list[dict[str, Any]]]] = []
    for cat in order:
        pending = balance_by_tier(groups.get(cat, []))
        cat_chunks: list[list[dict[str, Any]]] = []
        while pending:
            cat_chunks.append(pending[:batch])
            pending = pending[batch:]
        if cat_chunks:
            per_category.append(cat_chunks)

    # Round-robin the category queues: the first batch is misc, the second is
    # re, the third crypto, then misc again - "five misc, then five re", not
    # "all 300 misc, then all 200 re".
    chunks: list[list[dict[str, Any]]] = []
    index = 0
    while any(index < len(queue) for queue in per_category):
        for queue in per_category:
            if index < len(queue):
                chunks.append(queue[index])
        index += 1
    return chunks
