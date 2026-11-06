"""Checks for the category knowledge base."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import knowledge
from backend.prompts import ChallengeMeta, build_prompt


def main() -> None:
    assert knowledge.category_key("Web 安全与渗透测试") == "web"
    assert knowledge.category_key("二进制漏洞审计") == "pwn"
    assert knowledge.category_key("软件逆向工程") == "re"
    assert knowledge.category_key("现代密码学") == "crypto"
    assert knowledge.category_key("取证与安全杂项") == "misc"
    assert knowledge.category_key("unknown-thing") == "misc"
    print("mapping ok")

    for cat in ("web", "pwn", "re", "crypto", "misc"):
        text = knowledge.digest(cat)
        assert text and "##" in text, cat
    assert knowledge.digest("web", max_chars=80).endswith("…")
    print("digest ok")

    prompt = build_prompt(
        ChallengeMeta(name="x", category="web"), [], knowledge=knowledge.digest("web")
    )
    assert "经验清单" in prompt and "WEB 方向经验清单" in prompt
    plain = build_prompt(ChallengeMeta(name="x", category="web"), [])
    assert "经验清单" not in plain
    print("prompt ok")

    print("ALL KNOWLEDGE CHECKS PASSED")


if __name__ == "__main__":
    main()
