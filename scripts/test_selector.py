"""Offline checks for the drill-mode selector (backend/selector.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.selector import balance_by_tier, rotate_chunks, tier_of  # noqa: E402


def ch(name: str, category: str, difficulty: str = "") -> dict:
    return {"name": name, "category": category, "difficulty": difficulty}


def main() -> None:
    assert tier_of(ch("a", "misc", "简单")) == "简单"
    assert tier_of(ch("a", "misc", "")) == ""
    assert tier_of({"name": "x", "tags": ["MISC", "困难"]}) == "困难"

    # balance_by_tier interleaves tiers instead of draining the easy bucket.
    pool = (
        [ch(f"e{i}", "misc", "简单") for i in range(6)]
        + [ch(f"m{i}", "misc", "中等") for i in range(3)]
        + [ch(f"h{i}", "misc", "困难") for i in range(2)]
        + [ch(f"i{i}", "misc", "入门") for i in range(2)]
    )
    ordered = balance_by_tier(pool)
    assert len(ordered) == len(pool)
    head = [tier_of(c) for c in ordered[:4]]
    assert set(head) == {"困难", "中等", "简单", "入门"}, head

    # rotate_chunks hands out one direction per batch and respects the size.
    mixed = (
        [ch(f"misc{i}", "misc", "简单") for i in range(5)]
        + [ch(f"re{i}", "REVERSE", "中等") for i in range(4)]
        + [ch(f"pwn{i}", "pwn", "困难") for i in range(3)]
    )
    batches = rotate_chunks(mixed, 3)
    # Category queues are round-robined: misc, re, pwn, then misc, re again.
    assert [len(b) for b in batches] == [3, 3, 3, 2, 1], [len(b) for b in batches]
    cats = [b[0]["category"] for b in batches]
    assert cats == ["misc", "REVERSE", "pwn", "misc", "REVERSE"], cats
    # A batch must never mix directions.
    assert all(len({c["category"] for c in b}) == 1 for b in batches)

    # Explicit category order fixes who goes first, and every batch switches
    # direction instead of draining a whole category.
    ordered_batches = rotate_chunks(mixed, 2, category_order=("misc", "REVERSE", "pwn"))
    assert ordered_batches[0][0]["category"] == "misc"
    assert ordered_batches[1][0]["category"] == "REVERSE"
    assert ordered_batches[2][0]["category"] == "pwn"

    # Difficulty is balanced inside each batch.
    tough = [ch(f"hard{i}", "pwn", "困难") for i in range(2)] + [ch("easy1", "pwn", "简单")]
    first = rotate_chunks(tough, 3)[0]
    assert {tier_of(c) for c in first} == {"困难", "简单"}, [tier_of(c) for c in first]

    assert rotate_chunks([], 3) == []
    print("ALL SELECTOR CHECKS PASSED")


if __name__ == "__main__":
    main()
