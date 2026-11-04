"""Offline test for round mode (backend/round_runner.py).

Replaces the platform client and the challenge swarm with fakes, so it runs
without Docker, network or a real token.
Run with:  uv run python scripts/test_round_runner.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import round_runner  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.solver_base import FLAG_FOUND  # noqa: E402

CHALLENGES = [
    {"id": 1, "name": "Hard One", "category": "pwn", "value": 500, "description": "x"},
    {"id": 2, "name": "Easy One", "category": "misc", "value": 100, "description": "y"},
    {"id": 3, "name": "Solved One", "category": "web", "value": 50, "description": "z"},
]


class FakePlatform:
    def __init__(self, challenges, solved):
        self.challenges = challenges
        self.solved = solved
        self.pulled: list[str] = []
        self.closed = False

    async def fetch_all_challenges(self):
        return list(self.challenges)

    async def fetch_solved_names(self):
        return set(self.solved)

    async def pull_challenge(self, challenge, output_dir):
        self.pulled.append(challenge["name"])
        d = Path(output_dir) / challenge["name"].lower().replace(" ", "-")
        (d / "distfiles").mkdir(parents=True, exist_ok=True)
        (d / "metadata.yml").write_text(
            "name: " + challenge["name"] + "\ncategory: " + challenge["category"]
            + "\nvalue: " + str(challenge["value"]) + "\ndescription: " + challenge["description"] + "\n",
            encoding="utf-8",
        )
        return str(d)

    async def close(self):
        self.closed = True


class FakeResult:
    def __init__(self, status, flag=None):
        self.status = status
        self.flag = flag


class FakeSwarm:
    def __init__(self, challenge_dir, meta, **kwargs):
        self.meta = meta

    async def run(self):
        # "Easy One" solves, "Hard One" does not.
        if self.meta.name == "Easy One":
            return FakeResult(FLAG_FOUND, "flag{easy}")
        return FakeResult("failed")


async def main() -> int:
    problems = []

    settings = Settings(
        platform="ret2shell",
        ret2shell_url="https://r2s.test",
        ret2shell_token="tok",
        max_concurrent_challenges=2,
    )

    # ---- selection: unsolved only, filters, and pick orders
    pool = round_runner._filter_pool(CHALLENGES, {"Solved One"})
    assert [c["name"] for c in round_runner._pick(pool, 1, "score")] == ["Easy One"]
    assert [c["name"] for c in round_runner._pick(pool, 10, "score")] == ["Easy One", "Hard One"]
    assert [c["name"] for c in round_runner._pick(pool, 1, "name")] == ["Easy One"]
    picks = {round_runner._pick(pool, 1, "random")[0]["name"] for _ in range(40)}
    assert picks == {"Easy One", "Hard One"}, picks
    print("selection ok (orders: score / name / random, solved excluded, capped)")

    # ---- min_score / only filters
    assert [c["name"] for c in round_runner._filter_pool(CHALLENGES, set(), min_score=200)] == ["Hard One"]
    assert [c["name"] for c in round_runner._filter_pool(CHALLENGES, set(), only=("easy",))] == ["Easy One"]
    print("filters ok (min-score, only)")

    # ---- include_solved puts finished challenges back into the pool
    all_names = [c["name"] for c in round_runner._filter_pool(CHALLENGES, {"Solved One"}, include_solved=True)]
    assert "Solved One" in all_names and len(all_names) == 3, all_names
    assert "Solved One" not in [c["name"] for c in round_runner._filter_pool(CHALLENGES, {"Solved One"})]
    print("include-solved ok (solved challenges can re-enter the pool)")

    # ---- round run with fakes
    platform = FakePlatform(CHALLENGES, {"Solved One"})
    round_runner.make_platform = lambda s: platform
    round_runner.platform_kind = lambda s: "ret2shell"
    round_runner.ChallengeSwarm = FakeSwarm

    async def _noop():
        return None

    round_runner.cleanup_orphan_containers = _noop

    out_dir = "F:/ctf_agent/logs/round-test"
    history = Path(out_dir) / "history.json"
    history.unlink(missing_ok=True)
    settings.round_history_file = str(history)
    summary = await round_runner.run_round(
        settings=settings,
        model_specs=["deepseek/deepseek-flash"],
        round_size=2,
        challenges_dir=out_dir,
        order="score",
        cooldown_hours=0,
    )
    print("summary:", {k: v for k, v in summary.items() if k != "results"})
    assert summary["selected"] == 2, summary
    assert summary["solved"] == 1, summary
    assert summary["results"]["Easy One"]["status"] == "solved", summary
    assert summary["results"]["Hard One"]["status"] == "unsolved", summary
    assert platform.closed, "platform must be closed"
    assert set(platform.pulled) == {"Easy One", "Hard One"}, platform.pulled
    print("round ok: 2 pulled, 1 solved, platform closed")

    # ---- attempt history: names recorded, and an all-recent pool falls back to retry
    hist = round_runner._load_history(history)
    assert set(hist) == {"Easy One", "Hard One"}, hist
    platform2 = FakePlatform(CHALLENGES, {"Solved One"})
    round_runner.make_platform = lambda s: platform2
    summary2 = await round_runner.run_round(
        settings=settings,
        model_specs=["deepseek/deepseek-flash"],
        round_size=2,
        challenges_dir=out_dir,
        order="random",
        cooldown_hours=6,
    )
    assert summary2["selected"] == 2, summary2  # everything recent -> retry anyway
    print("history ok: attempts recorded, all-recent pool retried instead of stalling")

    # ---- include_solved: finished challenges take part in the round
    history.unlink(missing_ok=True)
    platform3 = FakePlatform(CHALLENGES, {"Solved One"})
    round_runner.make_platform = lambda s: platform3
    summary3 = await round_runner.run_round(
        settings=settings,
        model_specs=["deepseek/deepseek-flash"],
        round_size=3,
        challenges_dir=out_dir,
        order="name",
        cooldown_hours=6,
        include_solved=True,
    )
    assert summary3["selected"] == 3, summary3
    assert "Solved One" in summary3["results"], summary3
    assert "Solved One" in platform3.pulled, platform3.pulled
    print("include-solved round ok: solved challenge pulled and solved again")

    # ---- missing token: clean error, no crash
    settings_no_token = Settings(platform="ret2shell", ret2shell_url="https://r2s.test", ret2shell_token="")
    round_runner.make_platform = lambda s: FakePlatform(CHALLENGES, set())
    summary = await round_runner.run_round(settings_no_token, ["deepseek/deepseek-flash"], 3)
    assert summary.get("error") == "missing token", summary
    print("missing-token ok:", summary["error"])

    print("\nALL ROUND RUNNER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
