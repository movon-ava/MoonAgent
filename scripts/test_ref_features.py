"""Offline checks for the features borrowed from the reference Go agent.

Covers: submission de-duplication (sqlite), permanent pauses, the target-env
registry, and the platform request pacer.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import pauses, platformgate, submissions, targetenv  # noqa: E402


def check_submissions() -> None:
    # The sqlite file persists between runs, so each run gets a fresh scope.
    import uuid

    scope = submissions.scope_for("ctf2", "https://example.test", f"tok-{uuid.uuid4()}")
    flag = "  flag{dup_me}  "
    assert submissions.previous(scope, "Demo", flag) is None
    assert submissions.reserve(scope, "Demo", flag) is True
    assert submissions.reserve(scope, "Demo", flag) is False, "second reserve must fail"
    assert submissions.previous(scope, "Demo", flag)["status"] == "pending"
    submissions.record(scope, "Demo", flag, "incorrect", "nope")
    prev = submissions.previous(scope, "Demo", "flag{dup_me}")
    assert prev and prev["status"] == "incorrect" and prev["message"] == "nope"
    # A different scope (other account/platform) is independent.
    other = submissions.scope_for("ctf2", "https://example.test", f"tok-{uuid.uuid4()}")
    assert submissions.previous(other, "Demo", flag) is None
    print("submissions dedupe ok")


def check_pauses() -> None:
    pauses.clear()
    assert not pauses.is_paused("Hard One")
    pauses.pause("Hard One", "attempts exhausted")
    assert pauses.is_paused("hard one") is False  # names are case-sensitive
    assert pauses.is_paused("Hard One")
    assert "Hard One" in pauses.paused_names()
    assert pauses.view()[0]["reason"] == "attempts exhausted"
    assert pauses.unpause("Hard One") is True
    assert not pauses.is_paused("Hard One")
    print("pauses ok")


def check_targetenv() -> None:
    targetenv.clear()
    targetenv.register("Box A", ground_id="g1", challenge_id="c1", access_url="h:1")
    assert targetenv.get("Box A")["ground_id"] == "g1"
    assert "Box A" in targetenv.owned()
    targetenv.unregister("Box A")
    assert targetenv.get("Box A") is None
    print("targetenv ok")


async def check_gate() -> None:
    start = time.time()
    for _ in range(3):
        await platformgate.wait_turn(0.15)
    elapsed = time.time() - start
    assert elapsed >= 0.25, f"pacer too fast: {elapsed:.2f}s"
    # interval 0 is a no-op
    t0 = time.time()
    for _ in range(5):
        await platformgate.wait_turn(0)
    assert time.time() - t0 < 0.05
    print(f"platformgate ok ({elapsed:.2f}s for 3 paced calls)")


def main() -> None:
    check_submissions()
    check_pauses()
    check_targetenv()
    asyncio.run(check_gate())
    print("ALL REFERENCE-FEATURE CHECKS PASSED")


if __name__ == "__main__":
    main()
