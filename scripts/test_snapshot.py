"""Checks for run snapshots / resume helpers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import snapshot


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctf-snap-"))
    snapshot.RUNS_DIR = tmp / "runs"

    run_id = snapshot.new_run("ctfplus", 3, ["deepseek/deepseek-flash"])
    state = snapshot.load(run_id)
    assert state and state["platform"] == "ctfplus" and state["challenges"] == {}
    print("new/load ok", run_id)

    snapshot.update_challenge(run_id, "A", status="solved", flag="flag{a}")
    snapshot.update_challenge(run_id, "B", status="running")
    snapshot.update_challenge(run_id, "C", status="timeout")
    state = snapshot.load(run_id)
    assert state["challenges"]["A"]["flag"] == "flag{a}"
    assert set(snapshot.unfinished(state)) == {"B"}, snapshot.unfinished(state)
    print("unfinished ok")

    latest = snapshot.latest_open()
    assert latest and latest["run_id"] == run_id
    snapshot.finish(run_id)
    assert snapshot.latest_open() is None, "finished run must not be resumable"
    print("finish/latest_open ok")

    runs = snapshot.list_runs()
    assert runs and runs[0]["total"] == 3 and runs[0]["solved"] == 1
    print("stats ok")

    snapshot.update_challenge("no-such-run", "X", status="running")  # must not raise
    assert snapshot.load("no-such-run") is None
    print("missing run ok")

    print("ALL SNAPSHOT CHECKS PASSED")


if __name__ == "__main__":
    main()
