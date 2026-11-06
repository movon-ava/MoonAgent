"""Pytest gate over the existing ``scripts/test_*.py`` self-checks.

    uv run pytest              # fast checks (no Docker, no model calls)
    uv run pytest -m slow      # the expensive ones (sandbox image, real model)
    uv run pytest -m "slow or not slow"

Each script is executed in its own process; a non-zero exit fails the test and
the captured tail is attached to the report.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ROOT, run_script

#: needs Docker, the network, or a real model call
SLOW = {
    "test_solver_e2e",
    "test_sandbox_recovery",
    "test_coordinator_turn",
    "test_deepseek_pai",
    "test_project_deepseek",
}


def _scripts() -> list[Path]:
    return sorted((ROOT / "scripts").glob("test_*.py"))


def _cases() -> list[pytest.param]:
    cases = []
    for path in _scripts():
        mark = pytest.mark.slow if path.stem in SLOW else ()
        cases.append(pytest.param(path, marks=mark, id=path.stem))
    return cases


@pytest.mark.parametrize("script", _cases())
def test_selfcheck(script: Path) -> None:
    proc = run_script(script)
    if proc.returncode != 0:
        tail = (proc.stdout or "")[-3000:] + "\n" + (proc.stderr or "")[-3000:]
        pytest.fail(f"{script.name} exited {proc.returncode}\n{tail}")
