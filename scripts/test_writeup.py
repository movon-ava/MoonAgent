"""Offline checks for the writeup feature (no network, no sandbox)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.config import Settings
from backend.prompts import ChallengeMeta
from backend.writeup import build_prompt, render_markdown, trace_digest, write


def make_trace(tmp: Path) -> Path:
    path = tmp / "trace-demo.jsonl"
    events = [
        {"type": "start", "challenge": "demo", "model": "deepseek-flash"},
        {"type": "thinking", "text": "先看看附件"},
        {"type": "tool_call", "tool": "bash", "args": {"command": "file demo.bin"}},
        {"type": "tool_result", "result": "demo.bin: ELF 64-bit LSB executable"},
        {"type": "tool_call", "tool": "bash", "args": {"command": "python3 solve.py"}},
        {"type": "tool_result", "result": "flag{offline_demo}"},
        {"type": "flag_confirmed", "flag": "flag{offline_demo}"},
    ]
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    return path


class FakeResult:
    def __init__(self, flag: str, log_path: str):
        self.flag = flag
        self.log_path = log_path


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        trace = make_trace(tmp)

        digest = trace_digest(trace)
        assert "file demo.bin" in digest, digest
        assert "flag{offline_demo}" in digest, digest
        assert "先看看附件" in digest

        meta = ChallengeMeta(
            name="demo",
            category="pwn",
            value=100,
            description="一个演示题",
            tags=["Pwn", "简单"],
            challenge_dir=str(tmp / "challenges" / "demo"),
        )
        (tmp / "challenges" / "demo" / "distfiles").mkdir(parents=True)
        (tmp / "challenges" / "demo" / "distfiles" / "demo.bin").write_bytes(b"x")

        prompt = build_prompt(meta, "flag{offline_demo}", digest)
        for needle in ("demo", "pwn", "flag{offline_demo}", "file demo.bin", "demo.bin"):
            assert needle in prompt, needle
        print("prompt ok")

        settings = Settings(writeup_enabled=False, writeup_dir=str(tmp / "out"))
        res = FakeResult("flag{offline_demo}", str(trace))
        assert asyncio.run(write(settings, meta, res)) is None
        print("disabled ok")

        settings = Settings(writeup_enabled=True, writeup_dir=str(tmp / "out"))
        assert asyncio.run(write(settings, meta, FakeResult("", str(trace)))) is None
        print("empty flag ok")

        async def fake_runner(_settings, _prompt):
            assert "demo" in _prompt
            return "## 分析\n\n这里是正文。\n"

        path = asyncio.run(write(settings, meta, res, runner=fake_runner))
        assert path and Path(path).exists(), path
        text = Path(path).read_text(encoding="utf-8")
        assert text.startswith("# demo"), text[:40]
        assert "flag{offline_demo}" in text
        assert "这里是正文" in text
        assert Path(path).parent.name == "pwn"
        print("write ok:", Path(path).name)

        header = render_markdown(meta, "flag{x}", "body")
        assert "`flag{x}`" in header and "body" in header
        print("render ok")

    print("ALL WRITEUP CHECKS PASSED")


if __name__ == "__main__":
    main()
