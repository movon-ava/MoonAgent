"""Checks for the submit-with-evidence gate."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import memory
from backend.tools.flag import SUBMIT_BLOCKED, submit_flag

NAME = "_test_evidence_demo"


class FakeDeps:
    def __init__(self, require=True, no_submit=False):
        self.challenge_name = NAME
        self.practice_mode = False
        self.confirmed_flag = None
        self.no_submit = no_submit
        self.settings = SimpleNamespace(require_flag_evidence=require)
        self.calls: list[str] = []

        async def submit_fn(flag):
            self.calls.append(flag)
            return ("CORRECT — accepted.", True)

        self.submit_fn = submit_fn


def call(deps, flag, evidence=""):
    ctx = SimpleNamespace(deps=deps)
    return asyncio.run(submit_flag(ctx, flag, evidence))


def main() -> None:
    memory.clear(NAME)

    deps = FakeDeps()
    out = call(deps, "flag{a}")
    assert out == SUBMIT_BLOCKED and deps.calls == [], out
    print("blocked without evidence ok")

    out = call(deps, "flag{a}", "cat /challenge/distfiles/flag.txt printed flag{a}")
    assert out.startswith("CORRECT") and deps.calls == ["flag{a}"]
    assert deps.confirmed_flag == "flag{a}"
    notes = memory.digest(NAME)
    assert "evidence" in notes and "flag{a}" in notes
    print("submit with evidence ok")

    soft = FakeDeps(require=False)
    out = call(soft, "flag{b}")
    assert out.startswith("CORRECT") and soft.calls == ["flag{b}"]
    print("gate disabled ok")

    dry = FakeDeps(no_submit=True)
    out = call(dry, "flag{c}")
    assert out.startswith("DRY RUN") and dry.calls == []
    print("dry run ok")

    practice = FakeDeps()

    async def practice_submit(flag):
        practice.calls.append(flag)
        return ("PRACTICE - unverifiable", False)

    practice.submit_fn = practice_submit
    out = call(practice, "flag{d}", "derived from the RSA parameters")
    assert out.startswith("PRACTICE") and practice.practice_mode
    print("practice ok")

    memory.clear(NAME)
    print("ALL EVIDENCE CHECKS PASSED")


if __name__ == "__main__":
    main()
