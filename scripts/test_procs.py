"""Check the cross-platform process helpers used by the dashboard.

Run with:  uv run python scripts/test_procs.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import procs  # noqa: E402


def check_listing() -> None:
    names = ("python.exe", "python") if procs.WINDOWS else ("python", "python3")
    rows = procs.list_processes(names)
    pids = {pid for pid, _name, _cmd in rows}
    assert os.getpid() in pids, f"the test process itself must be listed: {sorted(pids)[:5]}"
    for pid, name, cmdline in rows:
        assert pid > 0, (pid, name)
        assert isinstance(cmdline, str)
    print(f"listing ok: {len(rows)} process(es)")

    fresh = procs.list_processes(names, min_age_s=10_000)
    assert os.getpid() not in {pid for pid, _n, _c in fresh}, "age filter must drop the test process"
    print("age filter ok")


def check_spawn_and_kill() -> None:
    code = "import time; time.sleep(120)"
    spawn: dict = {}
    if os.name == "nt":
        spawn["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        spawn["start_new_session"] = True
    child = subprocess.Popen([sys.executable, "-c", code], **spawn)
    try:
        time.sleep(0.5)
        assert procs.kill_tree(child.pid, timeout=5.0) is True
        deadline = time.time() + 10
        while time.time() < deadline and child.poll() is None:
            time.sleep(0.1)
        assert child.poll() is not None, "the child must be gone after kill_tree"
    finally:
        if child.poll() is None:
            child.kill()
    print("kill_tree ok")


def check_bad_input() -> None:
    for bad in (0, -1, "not-a-pid", None):
        assert procs.kill_tree(bad) is False, bad
    print("bad input ok")


def check_no_windows_leak() -> None:
    source = Path(procs.__file__).read_text(encoding="utf-8")
    assert "taskkill" in source and "killpg" in source, "both branches must exist"
    assert "start_new_session" in Path(ROOT / "backend" / "wsrx.py").read_text(encoding="utf-8")
    print("platform branches ok")


def main() -> int:
    check_no_windows_leak()
    check_listing()
    check_bad_input()
    check_spawn_and_kill()
    print("ALL PROCESS-HELPER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
