"""Platform selection — CTFd, Ret2Shell, DASCTF, CTF² Agent Arena or CTF+."""

from __future__ import annotations

import logging
from typing import Any

from backend.ctf2 import Ctf2Client
from backend.ctfd import CTFdClient
from backend.ctfplus import CtfplusClient
from backend.dasctf import DasctfClient
from backend.flagfmt import FlagFormatProxy
from backend.ret2shell import Ret2ShellClient, normalize_difficulties

logger = logging.getLogger(__name__)

# Accepted aliases for --platform / PLATFORM.
RET2SHELL_ALIASES = {"ret2shell", "r2s", "xidian", "moectf"}
DASCTF_ALIASES = {"dasctf", "ycb", "yangcheng", "pro"}
CTF2_ALIASES = {"ctf2", "arena", "agent-arena", "ctf2arena"}
CTFPLUS_ALIASES = {"ctfplus", "ctf+", "plus", "geek"}
CTFD_ALIASES = {"ctfd", "auto", ""}


def platform_kind(settings: Any) -> str:
    """Return ``"ret2shell"``, ``"dasctf"``, ``"ctf2"``, ``"ctfplus"`` or ``"ctfd"``."""
    raw = (getattr(settings, "platform", "") or "auto").strip().lower()
    if raw in RET2SHELL_ALIASES:
        return "ret2shell"
    if raw in DASCTF_ALIASES:
        return "dasctf"
    if raw in CTF2_ALIASES:
        return "ctf2"
    if raw in CTFPLUS_ALIASES:
        return "ctfplus"
    if raw in CTFD_ALIASES:
        if raw == "auto":
            # auto: Ret2Shell when a token is configured, DASCTF when an
            # access key is configured, CTF² when an agent token is set,
            # otherwise CTFd.
            if (getattr(settings, "ret2shell_token", "") or "").strip():
                return "ret2shell"
            if (getattr(settings, "dasctf_access_key", "") or "").strip():
                return "dasctf"
            if (getattr(settings, "ctf2_token", "") or "").strip():
                return "ctf2"
            if (getattr(settings, "ctfplus_token", "") or "").strip():
                return "ctfplus"
        return "ctfd"
    return "ctfd"


def _split_categories(value: Any) -> tuple[str, ...]:
    """Parse "web, misc, pwn" / "all" / "" into a tuple of direction aliases."""
    return tuple(part.strip().lower() for part in str(value or "").split(",") if part.strip())


def _difficulties(value: Any) -> tuple[str, ...]:
    """Parse the difficulty setting; invalid words are dropped with a warning."""
    try:
        return normalize_difficulties(str(value or ""))
    except ValueError:
        return ()


async def fetch_catalog(platform: Any, enrich: bool = False) -> list[dict[str, Any]]:
    """Fetch the challenge list, asking for details only when they are needed.

    Platforms that can answer the list in one request (DASCTF) accept
    ``enrich``; the others ignore it and return their usual payload.
    """
    fn = platform.fetch_all_challenges
    try:
        return await fn(enrich=enrich)
    except TypeError:
        if enrich:
            logger.debug("platform %s cannot enrich the catalog", type(platform).__name__)
        return await fn()


def make_platform(settings: Any) -> Any:
    """Build the platform client, wrapped with the configured flag rules."""
    return _wrap_flag_format(_make_platform(settings), settings)


def _wrap_flag_format(client: Any, settings: Any) -> Any:
    fmt = str(getattr(settings, "flag_format", "") or "")
    mode = str(getattr(settings, "flag_submit_mode", "full") or "full")
    if not fmt and mode == "full":
        return client
    return FlagFormatProxy(client, flag_format=fmt, submit_mode=mode)


def _make_platform(settings: Any) -> Any:
    """Build a platform client with the CTFdClient duck-typed interface."""
    kind = platform_kind(settings)
    categories = _split_categories(getattr(settings, "challenge_categories", ""))
    difficulties = _difficulties(getattr(settings, "challenge_difficulty", ""))
    if kind == "ret2shell":
        return Ret2ShellClient(
            base_url=getattr(settings, "ret2shell_url", "https://ctf.xidian.edu.cn"),
            token=getattr(settings, "ret2shell_token", ""),
            game=getattr(settings, "ret2shell_game", ""),
            categories=categories,
            difficulties=difficulties,
        )
    if kind == "dasctf":
        return DasctfClient(
            base_url=getattr(settings, "dasctf_url", "https://pro.dasctf.com"),
            access_key=getattr(settings, "dasctf_access_key", ""),
            categories=categories,
            difficulties=difficulties,
            # Practice runs (含已解题) should really submit, otherwise the solver
            # short-circuits on the platform's own "solved" flag.
            resubmit_solved=bool(getattr(settings, "round_include_solved", False)),
            environment_limit=int(getattr(settings, "max_environments", 0) or 0),
        )
    if kind == "ctf2":
        return Ctf2Client(
            base_url=getattr(settings, "ctf2_url", "https://ctf2.dasctf.com"),
            token=getattr(settings, "ctf2_token", ""),
            categories=categories,
            difficulties=difficulties,
            ground=getattr(settings, "ctf2_ground", ""),
            request_interval=float(getattr(settings, "platform_request_interval", 0.8) or 0.8),
        )
    if kind == "ctfplus":
        return CtfplusClient(
            base_url=getattr(settings, "ctfplus_url", "https://geek2026.play.ctfplus.cn"),
            token=getattr(settings, "ctfplus_token", ""),
            max_envs=int(getattr(settings, "max_environments", 0) or 0),
            categories=categories,
            difficulties=difficulties,
        )
    return CTFdClient(
        base_url=settings.ctfd_url,
        token=settings.ctfd_token,
        username=settings.ctfd_user,
        password=settings.ctfd_pass,
    )
