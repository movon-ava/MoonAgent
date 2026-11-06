"""Checks for fast-attack (speed) mode and the dead-target fast abort.

Run: uv run python scripts/test_blitz.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.selector import easy_first, easy_key  # noqa: E402

CHECKS = 0


def check(label: str, ok: bool) -> None:
    global CHECKS
    CHECKS += 1
    if not ok:
        print(f"  {label} FAILED")
        raise SystemExit(1)
    print(f"  {label} ok")


def main() -> None:
    pool = [
        {"name": "hard-one", "difficulty": "困难", "value": 500},
        {"name": "intro", "difficulty": "入门", "value": 100},
        {"name": "mid", "difficulty": "中等", "value": 300},
        {"name": "easy", "difficulty": "简单", "value": 200},
        {"name": "tagged", "tags": ["简单"], "value": 50},
    ]
    ordered = easy_first(pool)
    check(
        "easy-first order",
        [c["name"] for c in ordered] == ["intro", "tagged", "easy", "mid", "hard-one"],
    )
    check("difficulty tag respected", easy_key(pool[4])[0] == 1)

    settings = Settings(_env_file=None)
    check("blitz off by default", settings.blitz_mode is False)
    check("blitz budget unset", settings.blitz_max_challenges == 0)
    check("target-down limit default", settings.target_down_limit == 3)

    # A single mistyped .env line must not turn blitz on.
    check("blitz env parse", Settings(_env_file=None, blitz_mode=True).blitz_mode is True)

    # CLI wiring: the flags must exist and reach Settings.
    cli = (ROOT / "backend" / "cli.py").read_text(encoding="utf-8")
    check("cli has --blitz", '"--blitz/--no-blitz"' in cli)
    check("cli assigns blitz", "settings.blitz_mode = bool(blitz)" in cli)
    check("cli assigns blitz timeout", "settings.blitz_timeout_min = max(1.0, float(blitz_timeout))" in cli)

    runner = (ROOT / "backend" / "round_runner.py").read_text(encoding="utf-8")
    check("round runner forces easy order", 'order = "easy"' in runner)
    check("round runner blitz timeout", "blitz_timeout_min" in runner)

    # Dead-target abort is wired through deps, the tool gate, the solver and swarm.
    deps = (ROOT / "backend" / "deps.py").read_text(encoding="utf-8")
    check("deps counts target-down hits", "target_down_hits" in deps)
    gate = (ROOT / "backend" / "tools" / "sandbox.py").read_text(encoding="utf-8")
    check("gate increments hits", "deps.target_down_hits += 1" in gate)
    check("gate tells the model to stop", "Do not call more tools" in gate)
    solver = (ROOT / "backend" / "agents" / "solver.py").read_text(encoding="utf-8")
    check("solver watches dead target", "_watch_dead_target" in solver)
    check("solver reports target_down", 'self._result("target_down")' in solver)
    swarm = (ROOT / "backend" / "agents" / "swarm.py").read_text(encoding="utf-8")
    check("swarm aborts on target_down", 'result.status == "target_down"' in swarm)
    check("round records target_down", '"status": "target_down"' in runner)

    # Panel wiring.
    assets = (ROOT / "scripts" / "webui_assets.py").read_text(encoding="utf-8")
    check("panel has blitz checkbox", 'id="blitz_mode"' in assets)
    webui = (ROOT / "scripts" / "webui.py").read_text(encoding="utf-8")
    check("panel sends --blitz", 'argv.append("--blitz")' in webui)
    check("panel forces round mode", '"--round", "999"' in webui)

    print(f"ALL BLITZ CHECKS PASSED ({CHECKS} checks)")


if __name__ == "__main__":
    main()
