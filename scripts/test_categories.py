"""Offline tests for the Ret2Shell direction filter (web / misc / pwn / re / crypto)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ret2shell import (  # noqa: E402
    CATEGORY_ALIASES,
    difficulty_of,
    matches_categories,
    normalize_difficulties,
)

# Real category names of MoeCTF 2026 on ctf.xidian.edu.cn.
KEEP = [
    ("Web 安全与渗透测试", "web"),
    ("取证与安全杂项", "misc"),
    ("二进制漏洞审计", "pwn"),
    ("软件逆向工程", "re"),
    ("现代密码学", "crypto"),
]
DROP = ["Python 沙箱逃逸", "开发与运维基础", "策略与博弈", "大语言模型应用安全", "美工设计", "从此开始"]

WANTED = ("web", "misc", "pwn", "re", "crypto")


def main() -> int:
    for category, direction in KEEP:
        assert matches_categories(category, [category], WANTED), f"{category} should be kept"
        assert matches_categories(category, [category], (direction,)), (
            f"{category} should match direction {direction}"
        )
        assert not matches_categories(category, [category], tuple(d for d in WANTED if d != direction)), (
            f"{category} should NOT match other directions"
        )
    print(f"keep ok ({len(KEEP)} categories)")

    for category in DROP:
        assert not matches_categories(category, [category], WANTED), f"{category} should be dropped"
    print(f"drop ok ({len(DROP)} categories)")

    # Empty / "all" disables filtering.
    for disabled in ((), None, ("all",), ("",)):
        assert matches_categories("美工设计", ["美工设计"], disabled)
    print("disable ok (empty / all)")

    # Short ASCII alias must not match inside longer words.
    assert not matches_categories("Requiem", [], ("re",))
    assert matches_categories("RE", [], ("re",))
    assert matches_categories("reverse", [], ("re",))
    # DASCTF's replica spells the direction "REVRESE" (v/r transposed); a typo must
    # not hide the whole direction from the "re" filter or from the board.
    assert matches_categories("REVRESE", [], ("re",))
    assert not matches_categories("REVRESE", [], ("web",))
    print("word-boundary ok")

    # Unknown direction falls back to plain substring matching.
    assert matches_categories("Blockchain", ["Blockchain"], ("blockchain",))
    print("custom alias ok")

    assert set(CATEGORY_ALIASES) == set(WANTED)
    print("categories ok")

    # ---- difficulty tags (MoeCTF tags carry 入门/简单/中等/困难 as a second tag)
    assert difficulty_of(["软件逆向工程", "简单"], "软件逆向工程") == "简单"
    assert difficulty_of(["现代密码学"], "现代密码学") == ""
    assert difficulty_of(["简单"], "简单") == "简单"  # difficulty-only (no category) tag
    assert difficulty_of(["BASE编码"], "取证与安全杂项") == ""
    assert normalize_difficulties("easy,hard") == ("简单", "困难")
    assert normalize_difficulties("入门, 中等") == ("入门", "中等")
    assert normalize_difficulties("简单,简单") == ("简单",)
    assert normalize_difficulties("") == ()
    try:
        normalize_difficulties("impossible")
    except ValueError as exc:
        assert "unknown difficulty" in str(exc)
    else:
        raise AssertionError("invalid difficulty must raise")
    print("difficulty ok (aliases, empty, invalid)")

    print("\nALL CATEGORY FILTER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
