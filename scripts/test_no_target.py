"""Checks for the "no target environment" fast abort and the restart-on-start path."""

from __future__ import annotations

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.tools.sandbox import _target_gate  # noqa: E402


class FakeDeps:
    def __init__(self) -> None:
        self.challenge_name = "WEB - No Such Target"
        self.connection_info = ""
        self.needs_target = True
        self.target_down_hits = 0
        self.target_down_reason = ""
        self.notes: list[str] = []

    async def notify_coordinator(self, message: str) -> None:
        self.notes.append(message)


def check_gate() -> None:
    deps = FakeDeps()
    first = asyncio.run(_target_gate(deps))
    assert "NO TARGET yet" in first, first
    assert "STOP" not in first, "the first miss should only warn"
    assert deps.target_down_hits == 1
    assert deps.notes and "no target" in deps.notes[0]

    second = asyncio.run(_target_gate(deps))
    assert "STOP" in second, second
    assert "polling will not create an instance" in second
    assert deps.target_down_hits == 2
    print("gate ok: warns once, then asks the solver to stop")


def check_sources() -> None:
    dasctf = (ROOT / "backend" / "dasctf.py").read_text(encoding="utf-8")
    assert 'ch["has_container"] = bool(detail.get("isNeedInit"))' in dasctf
    assert '"has_container": bool(detail.get("isNeedInit"))' in dasctf

    runner = (ROOT / "backend" / "round_runner.py").read_text(encoding="utf-8")
    assert 'results[name] = {"flag": None, "status": "env_unavailable"}' in runner
    assert "skipped without spending tokens" in runner

    webui = (ROOT / "scripts" / "webui.py").read_text(encoding="utf-8")
    assert 'payload.get("restart")' in webui
    assert "_stop_locked" in webui

    assets = (ROOT / "scripts" / "webui_assets.py").read_text(encoding="utf-8")
    assert "function postStart" in assets
    assert "{restart:true}" in assets
    assert "当前有一轮在跑" in assets
    print("sources ok: env skip, has_container, restart path, JS confirm")


def check_meta_flag() -> None:
    from backend.prompts import ChallengeMeta

    meta = ChallengeMeta(name="x", has_container=True, connection_info="")
    assert meta.has_container and not meta.connection_info
    meta2 = ChallengeMeta(name="y", has_container=False)
    assert not meta2.has_container
    print("meta ok: has_container marks container challenges")


def main() -> None:
    check_gate()
    check_sources()
    check_meta_flag()
    print("ALL NO-TARGET / RESTART CHECKS PASSED")


if __name__ == "__main__":
    main()
