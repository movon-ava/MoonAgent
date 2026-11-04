"""Target reachability for challenges that expose a service.

The reference agent never let a solver guess where a target lives: if the
platform's endpoint is gone the run is told to rebuild it. We keep the same
rule — before every ``bash`` the solver re-checks the target it was given, and
a dead target fails fast with an actionable message instead of letting the model
spend a hundred tool calls scanning ``host.docker.internal``.
"""

from __future__ import annotations

import re
import socket
import time
from dataclasses import dataclass

# "host:port" or the CTF+ form "host port" (nc1.ctfplus.cn 36331).
_HOST_PORT_RE = re.compile(
    r"(?P<host>(?:\d{1,3}(?:\.\d{1,3}){3})|(?:[A-Za-z0-9][A-Za-z0-9._-]*\.[A-Za-z]{2,})|localhost)"
    r"[:\s](?P<port>\d{1,5})\b"
)
_URL_RE = re.compile(r"(?:https?|tcp|nc)://(?P<host>[^:/\s]+)(?::(?P<port>\d{1,5}))?")

# Hosts that only resolve inside a container but mean "this machine" for us.
_LOOPBACK_ALIASES = {"host.docker.internal", "gateway.docker.internal", "docker.for.mac.host.internal"}

CACHE_TTL_S = 30.0
_cache: dict[str, tuple[float, bool, str]] = {}


@dataclass(frozen=True)
class Target:
    host: str
    port: int

    def probe_host(self) -> str:
        return "127.0.0.1" if self.host.lower() in _LOOPBACK_ALIASES else self.host

    def label(self) -> str:
        return f"{self.host}:{self.port}"


def parse_targets(connection_info: str) -> list[Target]:
    """Extract every ``host:port`` mentioned in a ``connection_info`` block."""
    text = str(connection_info or "")
    found: list[Target] = []
    seen: set[tuple[str, int]] = set()
    for match in _HOST_PORT_RE.finditer(text):
        host = match.group("host")
        port = int(match.group("port"))
        if not (0 < port < 65536):
            continue
        key = (host.lower(), port)
        if key in seen:
            continue
        seen.add(key)
        found.append(Target(host, port))
    for match in _URL_RE.finditer(text):
        host, port = match.group("host"), match.group("port")
        if not port:
            continue
        key = (host.lower(), int(port))
        if key in seen:
            continue
        seen.add(key)
        found.append(Target(host, int(port)))
    return found


def _tcp_ok(target: Target, timeout: float) -> bool:
    try:
        with socket.create_connection((target.probe_host(), target.port), timeout=timeout):
            return True
    except OSError:
        return False


def check(connection_info: str, cache_key: str = "", timeout: float = 3.0) -> tuple[bool, str]:
    """Return ``(reachable, message)`` for the target behind ``connection_info``.

    No target configured (attachment-only challenge) is always "reachable" — the
    check only applies to challenges that were given a host:port.
    """
    targets = parse_targets(connection_info)
    if not targets:
        return True, ""
    key = cache_key or targets[0].label()
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_TTL_S:
        return cached[1], cached[2]
    for target in targets:
        if _tcp_ok(target, timeout):
            _cache[key] = (now, True, "")
            return True, ""
    message = (
        f"TARGET DOWN: cannot reach {', '.join(t.label() for t in targets)}. "
        "The challenge service is gone (instance expired or was replaced) - do NOT scan ports. "
        "Ask the coordinator to rebuild the target (spawn_swarm again / ensure_env), then retry."
    )
    _cache[key] = (now, False, message)
    return False, message


def forget(cache_key: str = "") -> None:
    if cache_key:
        _cache.pop(cache_key, None)
    else:
        _cache.clear()
