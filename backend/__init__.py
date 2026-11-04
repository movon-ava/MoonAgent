"""CTF Agent backend package.

Import-time environment hygiene that must happen before any HTTP client (httpx,
which is used by pydantic-ai's OpenAI-compatible provider) is constructed.
"""

from __future__ import annotations

import os
import sys


def _sanitize_no_proxy() -> None:
    """Drop IPv6 entries from NO_PROXY.

    httpx parses every NO_PROXY entry as a URL host pattern, so a value like
    ``localhost,127.0.0.1,::1,[::1]`` (common on Windows) makes it raise
    ``httpx.InvalidURL: Invalid port: ':1]'`` the moment a client is built.
    The IPv6 loopback is already covered by ``localhost``, so dropping those
    entries is safe.
    """
    raw = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    if not raw:
        return

    keep: list[str] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        bare = entry.strip("[]")
        if ":" in bare:  # IPv6 address or prefix — httpx cannot parse these
            continue
        keep.append(bare)

    cleaned = ",".join(keep) or "localhost,127.0.0.1"
    if cleaned != raw:
        os.environ["NO_PROXY"] = cleaned
        os.environ["no_proxy"] = cleaned


_sanitize_no_proxy()


def _force_utf8_stdio() -> None:
    """Avoid UnicodeEncodeError crashes on Windows (cp936 consoles).

    rich/click print progress glyphs (▶ ✔ →) and challenge names may contain
    emoji; a GBK console raises ``UnicodeEncodeError`` for those.  UTF-8 with
    ``errors="replace"`` never crashes, and modern terminals render it fine.

    The console input code page is switched to 65001 as well, otherwise Chinese
    hints typed by the operator arrive as GBK bytes and turn into mojibake.
    """
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetConsoleCP(65001)
            kernel32.SetConsoleOutputCP(65001)
        except Exception:  # noqa: BLE001 - not a real console (redirected)
            pass
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - e.g. redirected file objects
            pass


_force_utf8_stdio()
