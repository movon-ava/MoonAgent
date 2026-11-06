"""Checks for "run exactly the challenges I picked" (dashboard board selection).

Run: uv run python scripts/test_pick.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import snapshot  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.round_runner import run_round  # noqa: E402
from backend.solver_base import SolverResult  # noqa: E402
from scripts import webui  # noqa: E402

CHECKS = 0

NAMES = ["Pick Alpha", "Pick Beta", "Other Gamma"]


def check(label: str, ok: bool) -> None:
    global CHECKS
    CHECKS += 1
    if ok:
        print(f"  {label} ok")
    else:
        print(f"  {label} FAILED")
        raise SystemExit(1)


class FakePlatform:
    def __init__(self) -> None:
        self.pulled: list[str] = []

    async def fetch_all_challenges(self):
        return [
            {"name": n, "category": "misc", "value": 100, "has_container": False} for n in NAMES
        ]

    async def fetch_solved_names(self):
        return set()

    async def pull_challenge(self, ch, out_dir):
        self.pulled.append(ch["name"])
        d = Path(out_dir) / ch["name"].lower().replace(" ", "-")
        (d / "distfiles").mkdir(parents=True, exist_ok=True)
        (d / "metadata.yml").write_text(
            f"name: {ch['name']}\ncategory: misc\nvalue: 100\n", encoding="utf-8"
        )
        return str(d)

    async def max_environments(self):
        return 1

    async def close(self):
        pass


class FakeSwarm:
    def __init__(self, **kwargs) -> None:
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


def run_with_pick(pick: str, include_solved: bool = False) -> tuple[dict, FakePlatform]:
    tmp = Path(tempfile.mkdtemp(prefix="ctf-pick-"))
    challenges = tmp / "challenges"
    challenges.mkdir()
    snapshot.RUNS_DIR = tmp / "runs"

    import backend.round_runner as rr

    platform = FakePlatform()
    old_swarm, old_platform = rr.ChallengeSwarm, rr.make_platform
    rr.ChallengeSwarm = FakeSwarm  # type: ignore[assignment]
    rr.make_platform = lambda settings: platform  # type: ignore[assignment]
    try:
        settings = Settings(
            _env_file=None,
            platform="ctfplus",
            ctfplus_token="fake",
            ctfplus_url="https://example.invalid",
            round_size=3,
            max_concurrent_challenges=1,
            round_cooldown_hours=6,
            round_history_file=str(tmp / "history.json"),
            skip_solved_pull=False,
            round_rotate=False,
            fresh_solve=False,
            include_solved=include_solved,
            pick_challenges=pick,
        )
        result = asyncio.run(
            run_round(settings, ["deepseek/deepseek-flash"], 3, str(challenges), no_submit=True)
        )
    finally:
        rr.ChallengeSwarm, rr.make_platform = old_swarm, old_platform  # type: ignore[assignment]
    return result, platform


def main() -> None:
    # 1. Exact name: only that challenge runs, even with round_size 3.
    result, platform = run_with_pick("Pick Alpha")
    check("exact pick runs one", result.get("selected") == 1)
    check("exact pick name", list(result.get("results") or {}) == ["Pick Alpha"])
    check("other challenges not pulled", "Other Gamma" not in platform.pulled)

    # 2. Case-insensitive substring: "beta" matches "Pick Beta".
    result, _ = run_with_pick("beta")
    check("substring pick", list(result.get("results") or {}) == ["Pick Beta"])

    # 3. Two picks in one run.
    result, _ = run_with_pick("Pick Alpha,Pick Beta")
    check("multi pick", sorted(result.get("results") or {}) == ["Pick Alpha", "Pick Beta"])

    # 4. A name that is not on the platform must not silently run everything.
    result, platform = run_with_pick("No Such Challenge")
    check("unknown pick runs nothing", result.get("selected") == 0)
    check("unknown pick pulls nothing", platform.pulled == [])

    # 5. Panel wiring: the argv builder appends --pick for every name and forces
    #    round mode (the coordinator cannot be limited to a list).
    argv = webui._build_argv({"platform": "dasctf", "pick": ["Pick Alpha", "Pick Beta"]})
    check("argv has --pick", argv.count("--pick") == 2)
    check("argv pick value", "Pick Alpha" in argv and "Pick Beta" in argv)
    check("argv forces round mode", "--round" in argv)

    argv_plain = webui._build_argv({"platform": "dasctf"})
    check("no pick no flag", "--pick" not in argv_plain)

    cli = (ROOT / "backend" / "cli.py").read_text(encoding="utf-8")
    check("cli --pick option", '"--pick"' in cli and "settings.pick_challenges" in cli)
    assets = (ROOT / "scripts" / "webui_assets.py").read_text(encoding="utf-8")
    check("board pick bar", 'id="pickbar"' in assets and 'id="pick-run"' in assets)
    check("board sends pick", "form.pick = names" in assets)

    print(f"ALL PICK CHECKS PASSED ({CHECKS} checks)")


if __name__ == "__main__":
    main()
