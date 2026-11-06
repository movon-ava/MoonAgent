"""Housekeeping for log growth.

A busy day leaves hundreds of ``logs/trace-*.jsonl`` files (each up to a few MB)
plus one snapshot per round. Nothing prunes them, so ``logs/`` grows without
bound and the dashboard's file scans get slower every day.

``prune_logs()`` keeps the newest ``keep_traces`` traces (and anything from the
last ``days`` days), and drops run snapshots older than ``keep_run_days``.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
RUNS_DIR = LOG_DIR / "runs"

logger = logging.getLogger(__name__)


def prune_logs(
    days: float = 14.0,
    keep_traces: int = 200,
    keep_run_days: float = 30.0,
    dry_run: bool = False,
) -> dict[str, int]:
    removed = {"traces": 0, "runs": 0, "bytes": 0}
    if not LOG_DIR.exists():
        return removed

    cutoff = time.time() - max(0.0, days) * 86400
    traces = sorted(
        LOG_DIR.glob("trace-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for index, path in enumerate(traces):
        try:
            st = path.stat()
        except OSError:
            continue
        if index < keep_traces and st.st_mtime >= cutoff:
            continue
        removed["traces"] += 1
        removed["bytes"] += st.st_size
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                pass

    run_cutoff = time.time() - max(0.0, keep_run_days) * 86400
    if RUNS_DIR.exists():
        for run_dir in RUNS_DIR.iterdir():
            try:
                if not run_dir.is_dir() or run_dir.stat().st_mtime >= run_cutoff:
                    continue
                if not dry_run:
                    for child in run_dir.rglob("*"):
                        if child.is_file():
                            child.unlink(missing_ok=True)
                    for child in sorted(run_dir.rglob("*"), reverse=True):
                        if child.is_dir():
                            child.rmdir()
                    run_dir.rmdir()
                removed["runs"] += 1
            except OSError as exc:
                logger.debug("prune: cannot remove %s: %s", run_dir, exc)

    if removed["traces"] or removed["runs"]:
        logger.info(
            "pruned %s trace(s) and %s run(s), freed %.1f MB",
            removed["traces"],
            removed["runs"],
            removed["bytes"] / 1_048_576,
        )
    return removed
