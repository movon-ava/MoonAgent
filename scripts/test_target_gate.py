"""Container-slot gating in the coordinator path (one target at a time)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agents import coordinator_core
from backend.agents import swarm as swarm_module
from backend.agents.coordinator_core import _is_container, do_spawn_swarm
from backend.deps import CoordinatorDeps
from backend.prompts import ChallengeMeta


class FakePlatform:
    def __init__(self) -> None:
        self.pull_calls: list[str] = []
        self.stopped: list[str] = []
        self.challenges = [
            {"name": "web-one", "category": "web", "has_container": True},
            {"name": "crypto-docker", "category": "crypto", "has_container": True},
            {"name": "note", "category": "misc", "has_container": False},
        ]

    async def fetch_all_challenges(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return list(self.challenges)

    async def pull_challenge(self, ch, output_dir):  # noqa: ANN001, ANN003
        self.pull_calls.append(ch["name"])
        target = Path(output_dir) / ch["name"]
        target.mkdir(parents=True, exist_ok=True)
        (target / "metadata.yml").write_text(
            f"name: {ch['name']}\ncategory: {ch['category']}\n", encoding="utf-8"
        )
        return str(target)

    async def max_environments(self) -> int:
        return 1

    async def ensure_env(self, name: str) -> str:
        return f"target: 127.0.0.1:9999 ({name})"

    async def stop_env(self, name: str) -> bool:
        self.stopped.append(name)
        return True


class FakeSwarm:
    """Stand-in for ChallengeSwarm: never touches Docker, returns immediately."""

    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.cancel_event = SimpleNamespace(set=lambda: None)

    async def run(self):
        return SimpleNamespace(status="gave_up", flag=None)



def make_deps(platform: FakePlatform) -> CoordinatorDeps:
    deps = CoordinatorDeps(
        ctfd=platform,
        cost_tracker=SimpleNamespace(by_agent={}, record=lambda *a, **k: None),
        settings=SimpleNamespace(round_rotate=False, model_specs=[], max_concurrent_challenges=5),
        challenges_root="challenges",
        model_specs=[],
    )
    return deps


async def main() -> None:
    swarm_module.ChallengeSwarm = FakeSwarm
    assert _is_container(ChallengeMeta(name="x", category="crypto", has_container=True))
    assert not _is_container(ChallengeMeta(name="y", category="crypto"))

    platform = FakePlatform()
    deps = make_deps(platform)

    # Occupy the only target slot, then a container challenge must be rejected
    # *before* it pulls (pulling starts an instance and would steal the slot).
    deps.env_sem = asyncio.Semaphore(1)
    await deps.env_sem.acquire()
    msg = await do_spawn_swarm(deps, "crypto-docker")
    assert "Target capacity full" in msg, msg
    assert platform.pull_calls == [], platform.pull_calls

    # A non-container challenge is not gated by the target slot.
    deps.env_sem.release()
    deps = make_deps(platform)
    deps.env_sem = asyncio.Semaphore(1)
    await deps.env_sem.acquire()
    msg = await do_spawn_swarm(deps, "note")
    assert "Target capacity full" not in msg, msg
    assert platform.pull_calls == ["note"], platform.pull_calls
    for task in deps.swarm_tasks.values():
        task.cancel()

    # Every container challenge must destroy its target when the swarm ends
    # (solved, gave up, timeout or operator skip) - otherwise the single
    # platform slot stays consumed for the next run.
    platform2 = FakePlatform()
    deps2 = make_deps(platform2)
    swarm_module.ChallengeSwarm = FakeSwarm
    deps2.env_sem = asyncio.Semaphore(1)
    await do_spawn_swarm(deps2, "web-one")
    for task in list(deps2.swarm_tasks.values()):
        try:
            await asyncio.wait_for(task, timeout=30)
        except Exception:  # noqa: BLE001 - fake swarm may raise
            pass
    assert platform2.stopped == ["web-one"], platform2.stopped
    assert not deps2.env_sem.locked(), "target slot was not released"

    print("ALL TARGET GATE CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
