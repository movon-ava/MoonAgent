"""Offline checks for flag format hints and submit modes."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import Settings
from backend.flagfmt import (
    FlagFormatProxy,
    convert,
    describe,
    format_prefix,
    matches,
    normalize_format,
    normalize_mode,
)


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def submit_flag(self, name: str, flag: str):
        self.sent.append((name, flag))
        return f"correct:{flag}"

    async def fetch_challenge_stubs(self):
        return ["ok"]


def main() -> None:
    assert normalize_format("moectf") == "moectf{}"
    assert normalize_format("SYC{}") == "SYC{}"
    assert normalize_format("DASCTF{...}") == "DASCTF{}"
    assert normalize_format("") == ""
    assert format_prefix("flag{}") == "flag"
    print("normalize ok")

    assert normalize_mode("inner") == "inner"
    assert normalize_mode("FULL") == "full"
    assert normalize_mode("") == "full"
    print("mode ok")

    assert matches("moectf{abc}", "moectf{}") is True
    assert matches("flag{abc}", "moectf{}") is False
    assert matches("anything", "") is None
    print("matches ok")

    assert convert("moectf{abc}", "full") == "moectf{abc}"
    assert convert("moectf{abc}", "inner") == "abc"
    assert convert("DASCTF{a{b}c}", "inner") == "a{b}c"
    assert convert("plain", "inner") == "plain"
    print("convert ok")

    text = describe("SYC{}", "inner")
    assert "SYC{}" in text and "花括号" in text
    assert describe("", "full") == ""
    print("describe ok")

    inner = FakeClient()
    full_proxy = FlagFormatProxy(inner, "moectf{}", "full")
    assert asyncio.run(full_proxy.submit_flag("c", "moectf{abc}")) == "correct:moectf{abc}"
    inner_proxy = FlagFormatProxy(inner, "DASCTF{}", "inner")
    assert asyncio.run(inner_proxy.submit_flag("c", "DASCTF{abc}")) == "correct:abc"
    assert asyncio.run(inner_proxy.fetch_challenge_stubs()) == ["ok"]
    print("proxy ok")

    from backend.platform import _wrap_flag_format

    settings = Settings(flag_format="SYC{}", flag_submit_mode="inner")
    wrapped = _wrap_flag_format(FakeClient(), settings)
    assert isinstance(wrapped, FlagFormatProxy)
    plain = _wrap_flag_format(FakeClient(), Settings(flag_format="", flag_submit_mode="full"))
    assert not isinstance(plain, FlagFormatProxy)
    print("wiring ok")

    print("ALL FLAG-FORMAT CHECKS PASSED")


if __name__ == "__main__":
    main()
