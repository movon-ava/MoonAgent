"""Check per-challenge cost aggregation (solver traces -> round summary -> panel).

Run with:  uv run python scripts/test_cost_report.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import snapshot  # noqa: E402
from backend.cost_tracker import CostTracker  # noqa: E402


def check_by_challenge() -> None:
    tracker = CostTracker()
    tracker.record_tokens(
        "baby-pwn/deepseek/deepseek-flash", "deepseek-flash", input_tokens=1000, output_tokens=100
    )
    tracker.record_tokens(
        "baby-pwn/deepseek/deepseek-v4-pro", "deepseek-v4-pro", input_tokens=1000, output_tokens=100
    )
    tracker.record_tokens("web-login/deepseek/deepseek-flash", "deepseek-flash", input_tokens=500)
    tracker.record_tokens("coordinator", "deepseek-flash", input_tokens=2000)

    by_challenge = tracker.get_usage_by_challenge()
    assert set(by_challenge) == {"baby-pwn", "web-login", "coordinator"}, by_challenge
    assert by_challenge["baby-pwn"]["input"] == 2000, by_challenge["baby-pwn"]
    assert by_challenge["baby-pwn"]["cost"] > 0
    assert by_challenge["coordinator"]["cost"] > 0
    assert tracker.challenge_cost("baby-pwn") == by_challenge["baby-pwn"]["cost"]
    assert tracker.challenge_cost("never-ran") == 0.0
    total = sum(v["cost"] for v in by_challenge.values())
    assert abs(total - tracker.total_cost_usd) < 1e-9, (total, tracker.total_cost_usd)
    print(f"by-challenge ok: {sorted(by_challenge)} total ${total:.6f}")


def check_empty() -> None:
    tracker = CostTracker()
    assert tracker.get_usage_by_challenge() == {}
    assert tracker.challenge_cost("x") == 0.0
    tracker.log_challenge_summary()  # must not raise on an empty run
    print("empty tracker ok")


def check_snapshot_totals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        original = snapshot.RUNS_DIR
        snapshot.RUNS_DIR = Path(tmp) / "runs"
        try:
            run_id = snapshot.new_run("ctfd", 2, ["deepseek/deepseek-flash"])
            snapshot.update_challenge(run_id, "a", status="solved", cost_usd=0.25)
            snapshot.update_challenge(run_id, "b", status="failed", cost_usd=0.5)
            snapshot.update_challenge(run_id, "c", status="running")
            snapshot.finish(run_id)
            state = snapshot.load(run_id)
            assert state and state["finished"] is True
            runs = snapshot.list_runs(1)
            assert runs[0]["cost_usd"] == 0.75, runs[0].get("cost_usd")
            assert runs[0]["solved"] == 1 and runs[0]["total"] == 3, runs[0]
        finally:
            snapshot.RUNS_DIR = original
    print("snapshot totals ok")


def check_partial_usage() -> None:
    """A timed-out run still has to report the tokens it already burned."""
    src = (ROOT / "backend" / "agents" / "solver.py").read_text(encoding="utf-8")
    assert "usage=call_usage" in src, "solver no longer accumulates usage into a shared object"
    assert "except asyncio.CancelledError:" in src, "no cancellation hook to record partial usage"
    assert "self._usage_recorded" in src, "partial usage is not guarded against double counting"
    print("partial usage ok")


def main() -> int:
    check_empty()
    check_by_challenge()
    check_snapshot_totals()
    check_partial_usage()
    print("ALL COST-REPORT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
