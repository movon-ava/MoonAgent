"""Checks for the thinking-language toggle and skip-solved-on-pull."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.agents.coordinator_core import _platform_solved
from backend.config import Settings
from backend.prompts import ChallengeMeta, build_prompt


class FakePlatform:
    def __init__(self, names):
        self.names = set(names)
        self.calls = 0

    async def fetch_solved_names(self):
        self.calls += 1
        return self.names


def main() -> None:
    # read defaults from the code, not from the developer's .env (which may toggle them)
    s = Settings(_env_file=None)
    assert s.think_chinese is True, "default should keep Chinese thinking on"
    assert s.skip_solved_pull is True
    print("defaults ok")

    prompt_cn = build_prompt(ChallengeMeta(name="x"), [], think_chinese=True)
    prompt_en = build_prompt(ChallengeMeta(name="x"), [], think_chinese=False)
    assert "思考语言" in prompt_cn
    assert "思考语言" not in prompt_en
    print("prompt toggle ok")

    deps = SimpleNamespace(ctfd=FakePlatform({"a", "b"}), solved_cache=None)
    first = asyncio.run(_platform_solved(deps))
    second = asyncio.run(_platform_solved(deps))
    assert first == {"a", "b"} and second == {"a", "b"}
    assert deps.ctfd.calls == 1, "solved set must be cached for the run"
    print("cache ok")

    deps2 = SimpleNamespace(ctfd=SimpleNamespace(), solved_cache=None)
    assert asyncio.run(_platform_solved(deps2)) == set()
    print("no-fetcher ok")


    from backend.agents.coordinator_core import do_spawn_swarm

    class SpawnPlatform:
        async def fetch_solved_names(self):
            return {"already-done"}

    spawn_settings = Settings(
        round_rotate=False,
        round_include_solved=False,
        skip_solved_pull=True,
        model_specs="",
    )
    spawn_deps = SimpleNamespace(
        settings=spawn_settings,
        ctfd=SpawnPlatform(),
        swarms={},
        swarm_tasks={},
        max_concurrent_challenges=5,
        solved_cache=None,
        challenge_dirs={},
        challenge_metas={},
        results={},
        attempted=set(),
        attempt_counts={},
        model_specs=["deepseek/deepseek-flash"],
    )
    msg = asyncio.run(do_spawn_swarm(spawn_deps, "already-done"))
    assert "already solved" in msg, msg
    print("spawn skip ok:", msg[:60])

    print("ALL THINK/SKIP CHECKS PASSED")


if __name__ == "__main__":
    main()
