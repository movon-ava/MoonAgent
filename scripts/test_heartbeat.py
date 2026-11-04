"""Offline checks for the target heartbeat and reachability probe."""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import heartbeat, targets  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_parse() -> None:
    ctf2 = "target: 542ca541.ctf2.example:9999 (TLS) [nc]\n- nc: 542ca541.ctf2.example:9999 (TLS)"
    parsed = targets.parse_targets(ctf2)
    assert [(t.host, t.port) for t in parsed] == [
        ("542ca541.ctf2.example", 9999)
    ], parsed

    r2s = "target: abc123 (WSRX tunnel to this machine)\n- port 8080: host.docker.internal:41000 (via WSRX tunnel)"
    parsed = targets.parse_targets(r2s)
    assert any(t.host == "host.docker.internal" and t.port == 41000 for t in parsed), parsed
    assert parsed[0].probe_host() == "127.0.0.1", parsed[0]

    plus = "target: nc1.ctfplus.cn 36331\n\n  - nc: nc1.ctfplus.cn 36331"
    parsed = targets.parse_targets(plus)
    assert [(t.host, t.port) for t in parsed] == [("nc1.ctfplus.cn", 36331)], parsed

    url = "- url: http://80-9f0dfd63.challenge.ctfplus.cn"
    parsed = targets.parse_targets(url)
    assert parsed == [], parsed  # no port -> nothing to probe

    assert targets.parse_targets("") == []


def test_probe() -> None:
    targets.forget()
    port = _free_port()
    server = socket.socket()
    server.bind(("127.0.0.1", port))
    server.listen(1)
    try:
        ok, message = targets.check(f"target: 127.0.0.1:{port}", cache_key="up")
        assert ok and message == "", message
    finally:
        server.close()

    dead = _free_port()
    targets.forget()
    ok, message = targets.check(f"target: 127.0.0.1:{dead}", cache_key="down")
    assert not ok and "TARGET DOWN" in message, message
    # Cached: the second call must not hit the socket again (same message).
    ok2, message2 = targets.check(f"target: 127.0.0.1:{dead}", cache_key="down")
    assert not ok2 and message2 == message

    # A challenge without a target never blocks the sandbox.
    ok3, _ = targets.check("", cache_key="none")
    assert ok3


class FakePlatform:
    def __init__(self) -> None:
        self.renewed: list[str] = []

    async def renew_env(self, name: str) -> bool:
        self.renewed.append(name)
        return True


class NoRenewPlatform:
    pass


def test_heartbeat() -> None:
    async def run() -> None:
        heartbeat.clear()
        assert heartbeat.active_names() == []
        heartbeat.track("alpha")
        heartbeat.track("beta")
        assert sorted(heartbeat.active_names()) == ["alpha", "beta"]

        platform = FakePlatform()
        beat = heartbeat.EnvHeartbeat(platform, interval=60)
        count = await beat.beat()
        assert count == 2 and sorted(platform.renewed) == ["alpha", "beta"], platform.renewed

        heartbeat.untrack("alpha")
        platform.renewed.clear()
        await beat.beat()
        assert platform.renewed == ["beta"], platform.renewed

        # A platform without renew_env() must not spawn a loop.
        quiet = heartbeat.EnvHeartbeat(NoRenewPlatform(), interval=60)
        quiet.start()
        assert quiet._task is None
        await quiet.stop()

        # start()/stop() around a real (short) interval must not raise.
        beat2 = heartbeat.EnvHeartbeat(platform, interval=0.2)
        beat2.interval = 0.05
        beat2.start()
        await asyncio.sleep(0.12)
        await beat2.stop()
        heartbeat.clear()

    asyncio.run(run())


def test_gate() -> None:
    """The bash tool must refuse to run when the target is gone."""
    from backend.deps import SolverDeps
    from backend.tools.sandbox import _target_gate

    async def run() -> None:
        dead = _free_port()
        targets.forget("gate")
        deps = SolverDeps(
            sandbox=None,  # never touched when the gate blocks
            ctfd=None,
            challenge_dir="challenges/x",
            challenge_name="gate",
            workspace_dir="",
            use_vision=False,
            connection_info=f"target: 127.0.0.1:{dead}",
        )
        message = await _target_gate(deps)
        assert message.startswith("TARGET DOWN"), message

        # Attachment-only challenges (no connection_info) pass straight through.
        plain = SolverDeps(
            sandbox=None,
            ctfd=None,
            challenge_dir="challenges/y",
            challenge_name="plain",
            workspace_dir="",
            use_vision=False,
        )
        assert await _target_gate(plain) == ""

    asyncio.run(run())


def main() -> None:
    test_parse()
    print("parse ok")
    test_probe()
    print("probe ok")
    test_heartbeat()
    print("heartbeat ok")
    test_gate()
    print("gate ok")
    print("ALL HEARTBEAT CHECKS PASSED")


if __name__ == "__main__":
    main()
