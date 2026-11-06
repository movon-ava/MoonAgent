"""Check that log housekeeping keeps the newest traces and drops stale ones."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import maintenance


def _touch(path: Path, age_days: float, size: int = 1024) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    os.utime(path.parent, (stamp, stamp))


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctf-logs-"))
    maintenance.LOG_DIR = tmp / "logs"
    maintenance.RUNS_DIR = maintenance.LOG_DIR / "runs"

    for i in range(5):
        _touch(maintenance.LOG_DIR / f"trace-old{i}.jsonl", age_days=40)
    for i in range(3):
        _touch(maintenance.LOG_DIR / f"trace-new{i}.jsonl", age_days=1)
    _touch(maintenance.RUNS_DIR / "20250101-000000" / "state.json", age_days=60)
    _touch(maintenance.RUNS_DIR / "20261101-000000" / "state.json", age_days=1)

    dry = maintenance.prune_logs(dry_run=True)
    assert dry["traces"] == 5, dry
    assert len(list(maintenance.LOG_DIR.glob("trace-*.jsonl"))) == 8, "dry run must not delete"

    removed = maintenance.prune_logs(days=14, keep_traces=3, keep_run_days=30)
    assert removed["traces"] == 5, removed
    assert removed["runs"] == 1, removed
    left = sorted(p.name for p in maintenance.LOG_DIR.glob("trace-*.jsonl"))
    assert left == ["trace-new0.jsonl", "trace-new1.jsonl", "trace-new2.jsonl"], left
    assert not (maintenance.RUNS_DIR / "20250101-000000").exists()
    assert (maintenance.RUNS_DIR / "20261101-000000" / "state.json").exists()
    print("ALL MAINTENANCE CHECKS PASSED")


if __name__ == "__main__":
    main()
