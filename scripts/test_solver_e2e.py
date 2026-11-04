"""End-to-end smoke test: Docker sandbox + DeepSeek solver on a trivial challenge.

Run:  uv run python scripts\\test_solver_e2e.py
"""

import asyncio
import textwrap
from pathlib import Path

from backend.agents.solver import Solver
from backend.config import Settings
from backend.cost_tracker import CostTracker
from backend.prompts import ChallengeMeta

CHALLENGE_DIR = Path("challenges") / "smoke-deepseek"


def prepare_challenge() -> None:
    distfiles = CHALLENGE_DIR / "distfiles"
    distfiles.mkdir(parents=True, exist_ok=True)
    (distfiles / "flag.txt").write_text("flag{deepseek_sandbox_ok}\n", encoding="utf-8")
    (CHALLENGE_DIR / "metadata.yml").write_text(
        textwrap.dedent(
            """\
            name: smoke-deepseek
            category: misc
            value: 10
            description: |
              Trivial smoke test. The flag is stored in distfiles/flag.txt.
            tags: [smoke]
            """
        ),
        encoding="utf-8",
    )


async def main() -> None:
    prepare_challenge()
    settings = Settings()
    solver = Solver(
        model_spec="deepseek/deepseek-flash",
        challenge_dir=str(CHALLENGE_DIR),
        meta=ChallengeMeta.from_yaml(CHALLENGE_DIR / "metadata.yml"),
        ctfd=None,
        cost_tracker=CostTracker(),
        settings=settings,
    )
    solver.deps.no_submit = True
    try:
        await solver.start()
        print("sandbox workspace:", solver.sandbox.workspace_dir)
        probe = await solver.sandbox.exec("uname -m; ls -la /challenge/distfiles; cat /challenge/metadata.yml")
        print("--- sandbox probe ---")
        print(probe.stdout.strip())
        print("--- solver run ---")
        result = await solver.run_until_done_or_gave_up()
        print("result:", result)
    finally:
        await solver.stop()


asyncio.run(main())
