"""Offline check of the coordinator drill gate (backend/agents/coordinator_core)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agents.coordinator_core import drill_allow, drill_enabled  # noqa: E402
from backend.deps import CoordinatorDeps  # noqa: E402


class FakeCtfd:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch_all_challenges(self):
        self.calls += 1
        return (
            [{"name": f"web{i}", "category": "web", "solved": False} for i in range(1, 4)]
            + [{"name": f"misc{i}", "category": "misc", "solved": False} for i in range(1, 3)]
        )


def make_deps(rotate: bool = True, batch: int = 2) -> CoordinatorDeps:
    settings = SimpleNamespace(
        round_rotate=rotate,
        rotate_batch=batch,
        max_concurrent_challenges=5,
        challenge_categories="web,misc",
    )
    return CoordinatorDeps(ctfd=FakeCtfd(), cost_tracker=None, settings=settings)


async def main() -> None:
    deps = make_deps()
    assert drill_enabled(deps)

    # First batch is web (order hint), size 2.
    assert await drill_allow(deps, "web1") is None
    second = await drill_allow(deps, "web2")
    assert second and second.startswith("Batch finished"), second
    assert deps.drill_category == "misc", deps.drill_category

    # Off-direction spawns are rejected with the current batch listed.
    blocked = await drill_allow(deps, "web3")
    assert blocked and "misc" in blocked, blocked

    assert await drill_allow(deps, "misc1") is None
    last = await drill_allow(deps, "misc2")
    assert last and last.startswith("Batch finished"), last
    # After the last batch the coordinator reloads a fresh set and starts again
    # from the first direction, so an off-direction spawn is blocked again.
    reloaded = await drill_allow(deps, "misc1")
    assert reloaded and "web" in reloaded, reloaded

    # Drill disabled -> gate is a no-op.
    plain = make_deps(rotate=False)
    assert not drill_enabled(plain)
    print("ALL DRILL GATE CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
