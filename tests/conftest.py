"""Shared fixtures for the pytest gate.

Most checks live in ``scripts/test_*.py`` (they double as manual smoke tools).
The suite here runs each of them in its own process: some of them monkeypatch
module globals, write to ``logs/`` or spin up asyncio loops, so isolation keeps
one failure from poisoning the next.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


def run_script(script: Path, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
