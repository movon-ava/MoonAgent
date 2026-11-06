"""Run the whole self-check battery under coverage and print a total.

The checks live in ``scripts/test_*.py`` and mostly run in subprocesses, so
plain ``pytest --cov`` would only measure the test harness itself. Here each
script is executed with ``coverage run --parallel-mode`` and the data files are
combined before reporting, which gives real numbers for ``backend/``.

    uv run python scripts/coverage_report.py
    uv run python scripts/coverage_report.py --include-slow --fail-under 55
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SLOW = {
    "test_solver_e2e",
    "test_sandbox_recovery",
    "test_coordinator_turn",
    "test_deepseek_pai",
    "test_project_deepseek",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Coverage over the self-check battery")
    parser.add_argument("--include-slow", action="store_true", help="also run Docker/model checks")
    parser.add_argument("--fail-under", type=float, default=0.0, help="exit 1 below this percent")
    args = parser.parse_args()

    scripts = sorted((ROOT / "scripts").glob("test_*.py"))
    if not args.include_slow:
        scripts = [s for s in scripts if s.stem not in SLOW]

    failures: list[str] = []
    for script in scripts:
        proc = subprocess.run(  # noqa: S603 - fixed argv
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--parallel-mode",
                "--source=backend",
                str(script),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        status = "ok" if proc.returncode == 0 else "FAIL"
        print(f"[{status}] {script.name}")
        if proc.returncode != 0:
            failures.append(script.name)
            tail = ((proc.stdout or "") + (proc.stderr or ""))[-600:]
            print("  " + tail.replace("\n", "\n  "))

    subprocess.run([sys.executable, "-m", "coverage", "combine"], cwd=ROOT, check=False)
    report = subprocess.run(
        [sys.executable, "-m", "coverage", "report", "--skip-covered"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(report.stdout)
    total_line = [ln for ln in report.stdout.splitlines() if ln.startswith("TOTAL")]
    total = float(total_line[0].split()[-1].rstrip("%")) if total_line else 0.0

    if failures:
        print(f"failing checks: {', '.join(failures)}")
        return 1
    if total < args.fail_under:
        print(f"coverage {total:.1f}% is below the {args.fail_under:.1f}% threshold")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
