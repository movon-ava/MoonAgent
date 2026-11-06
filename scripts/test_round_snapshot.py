"""End-to-end check that a round writes a resumable snapshot."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import snapshot
from backend.config import Settings
from backend.round_runner import run_round
from backend.solver_base import SolverResult


class FakePlatform:
    def __init__(self):
        self.closed = False

    async def fetch_all_challenges(self):
        return [
            {"name": "Snap One", "category": "misc", "value": 10, "has_container": False},
            {"name": "Snap Two", "category": "misc", "value": 20, "has_container": False},
        ]

    async def fetch_solved_names(self):
        return set()

    async def pull_challenge(self, ch, out_dir):
        d = Path(out_dir) / ch["name"].lower().replace(" ", "-")
        (d / "distfiles").mkdir(parents=True, exist_ok=True)
        (d / "metadata.yml").write_text(
            f"name: {ch['name']}\ncategory: misc\nvalue: {ch['value']}\n", encoding="utf-8"
        )
        return str(d)

    async def max_environments(self):
        return 1

    async def close(self):
        self.closed = True


class FakeSwarm:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.cancel_event = asyncio.Event()

    async def run(self):
        name = self.kwargs["meta"].name
        return SolverResult(
            flag=f"flag{{{name}}}",
            status="flag_found",
            findings_summary="",
            step_count=1,
            cost_usd=0.0,
            log_path="",
        )


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctf-round-"))
    snapshot.RUNS_DIR = tmp / "runs"

    import backend.round_runner as rr

    old_swarm, old_platform = rr.ChallengeSwarm, rr.make_platform
    rr.ChallengeSwarm = FakeSwarm  # type: ignore[assignment]
    rr.make_platform = lambda settings: FakePlatform()  # type: ignore[assignment]
    try:
        settings = Settings(
            platform="ctfplus",
            round_size=2,
            max_concurrent_challenges=1,
            round_cooldown_hours=0,
            round_history_file=str(tmp / "history.json"),
            skip_solved_pull=False,
            round_rotate=False,
        )
        result = asyncio.run(
            run_round(settings, ["deepseek/deepseek-flash"], 2, str(tmp), no_submit=True)
        )
    finally:
        rr.ChallengeSwarm, rr.make_platform = old_swarm, old_platform  # type: ignore[assignment]

    assert result["solved"] == 2, result
    runs = list((tmp / "runs").glob("*/state.json"))
    assert runs, "round must write logs/runs/<id>/state.json"
    state = snapshot.load(runs[0].parent.name)
    assert state and state["finished"] is True, state
    assert {c["status"] for c in state["challenges"].values()} == {"solved"}, state["challenges"]
    print("round snapshot ok:", sorted(state["challenges"]))


if __name__ == "__main__":
    main()
