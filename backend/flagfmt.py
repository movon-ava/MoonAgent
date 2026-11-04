"""Flag format + submission mode shared by every platform adapter.

Two knobs, set in 配置 → 平台配置 (or ``FLAG_FORMAT`` / ``FLAG_SUBMIT_MODE``):

``flag_format``
    A human hint such as ``moectf{}``, ``SYC{}`` or ``DASCTF{}``. It is injected
    into the solver prompt so the model knows what a valid flag looks like, and
    used for a soft sanity check on submission (a mismatch only logs).

``flag_submit_mode``
    ``full`` sends the flag exactly as derived; ``inner`` strips the
    ``PREFIX{...}`` wrapper and sends only the content, which some platforms
    (DASCTF, 羊城杯) require.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

MODES = {"full": "提交完整 flag", "inner": "只提交花括号内的内容"}
_WRAPPER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-]*\{(?P<inner>.*)\}$", re.S)


def normalize_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in ("inner", "content", "inside", "bare"):
        return "inner"
    if text in ("full", "complete", "whole", ""):
        return "full"
    return "full"


def normalize_format(value: Any) -> str:
    """``moectf`` / ``moectf{}`` / ``moectf{...}`` -> ``moectf{}``."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace(" ", "")
    if "{" in text:
        prefix = text.split("{", 1)[0]
        return f"{prefix}{{}}"
    return f"{text}{{}}"


def format_prefix(flag_format: str) -> str:
    text = normalize_format(flag_format)
    return text.split("{", 1)[0] if "{" in text else text


def matches(flag: str, flag_format: str) -> bool | None:
    """Soft check: does ``flag`` look like ``flag_format``? None = no format set."""
    prefix = format_prefix(flag_format)
    if not prefix:
        return None
    return str(flag or "").strip().startswith(prefix + "{")


def convert(flag: str, mode: str) -> str:
    """Apply the submission mode to the flag the solver produced."""
    text = str(flag or "").strip()
    if normalize_mode(mode) != "inner":
        return text
    match = _WRAPPER_RE.match(text)
    if match:
        inner = match.group("inner").strip()
        if inner:
            return inner
    return text


def describe(flag_format: str = "", submit_mode: str = "full") -> str:
    """One prompt-ready paragraph; empty string when nothing is configured."""
    fmt = normalize_format(flag_format)
    mode = normalize_mode(submit_mode)
    parts: list[str] = []
    if fmt:
        parts.append(
            f"本场比赛的 flag 形如 `{fmt}`（例如 `{fmt.replace('{}', 'abc')}`），"
            "题目里另有说明时以题目为准。"
        )
    if mode == "inner":
        parts.append(
            "提交时平台只接受花括号内的内容：你仍然要在分析中给出完整 flag，"
            "但交给 `submit_flag` 的可以是完整 flag（客户端会自动去掉前缀与花括号）。"
        )
    elif fmt:
        parts.append("提交时给 `submit_flag` 完整 flag（含前缀和花括号）。")
    return " ".join(parts)


class FlagFormatProxy:
    """Wraps a platform client and rewrites the flag right before submission."""

    def __init__(self, inner: Any, flag_format: str = "", submit_mode: str = "full") -> None:
        self._inner = inner
        self._format = normalize_format(flag_format)
        self._mode = normalize_mode(submit_mode)
        self._warned = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def submit_flag(self, challenge_name: str, flag: str) -> Any:
        if self._format and not self._warned:
            ok = matches(flag, self._format)
            if ok is False:
                logger.warning(
                    "flag %r does not match the configured format %s (submitting anyway)",
                    str(flag)[:40],
                    self._format,
                )
                self._warned = True
        return await self._inner.submit_flag(challenge_name, convert(flag, self._mode))
