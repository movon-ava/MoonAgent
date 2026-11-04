import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agents.coordinator_core import _spawnable, do_fetch_challenges, include_solved


class FakeCtfd:
    async def fetch_all_challenges(self):
        return [
            {"name": "a", "category": "web", "value": 100, "solved": True},
            {"name": "b", "category": "pwn", "value": 200, "solved": False},
        ]

    async def fetch_solved_names(self):
        return {"a"}


def deps(allow: bool):
    return SimpleNamespace(
        settings=SimpleNamespace(round_include_solved=allow),
        swarms={},
        results={},
        ctfd=FakeCtfd(),
    )


async def main() -> None:
    assert include_solved(deps(True)) and not include_solved(deps(False))
    names_off = [c["name"] for c in _spawnable(deps(False), await FakeCtfd().fetch_all_challenges())]
    names_on = [c["name"] for c in _spawnable(deps(True), await FakeCtfd().fetch_all_challenges())]
    assert names_off == ["b"], names_off
    assert names_on == ["a", "b"], names_on

    off = await do_fetch_challenges(deps(False))
    on = await do_fetch_challenges(deps(True))
    assert '"include_solved": false' in off
    assert '"spawnable": false' in off.split('"name": "a"')[1][:400]
    assert '"include_solved": true' in on
    print("INCLUDE-SOLVED COORDINATOR CHECKS PASSED")


asyncio.run(main())
