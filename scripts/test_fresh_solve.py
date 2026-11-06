"""Checks for the fresh (evaluation) mode: no memory in, no memory out, no leftovers."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import memory, round_runner  # noqa: E402
from backend.agents import solver as solver_mod  # noqa: E402

OK = 0


def check(cond: bool, label: str) -> None:
    global OK
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    OK += 1
    print(f"ok: {label}")


def tool_names(fresh: bool) -> set[str]:
    deps = SimpleNamespace(
        settings=SimpleNamespace(fresh_solve=fresh),
        use_vision=False,
    )
    toolset = solver_mod._build_toolset(deps)
    return set(toolset.tools)


def main() -> None:
    plain = tool_names(False)
    clean = tool_names(True)
    check({"remember", "recall"} <= plain, "normal mode exposes remember/recall")
    check(not ({"remember", "recall"} & clean), "fresh mode hides remember/recall")
    check(len(plain) - len(clean) == 2, "fresh mode only drops the two memory tools")

    with tempfile.TemporaryDirectory() as tmp:
        original = memory.MEM_DIR
        memory.MEM_DIR = Path(tmp)
        try:
            path = Path(memory.note("demo", "flag", "flag{leaked_from_last_round}"))
            check(path.exists() and "leaked" in path.read_text(encoding="utf-8"), "note written")
            digest = memory.digest("demo")
            check("leaked" in digest, "digest would leak into the prompt without fresh mode")
        finally:
            memory.MEM_DIR = original

    # The submit tool must not record evidence/flags when the run is an evaluation.
    src = (Path(__file__).resolve().parents[1] / "backend" / "tools" / "flag.py").read_text(encoding="utf-8")
    check("fresh = bool(getattr(settings, \"fresh_solve\", False))" in src, "submit_flag reads fresh_solve")
    check(src.count("not fresh") >= 2, "submit_flag skips memory writes in fresh mode")

    solver_src = (Path(__file__).resolve().parents[1] / "backend" / "agents" / "solver.py").read_text(encoding="utf-8")
    check('"" if getattr(self.settings, "fresh_solve", False)' in solver_src, "prompt drops prior notes in fresh mode")
    check("and not getattr(self.settings, \"fresh_solve\", False)" in solver_src, "findings not persisted in fresh mode")

    rr_src = (Path(__file__).resolve().parents[1] / "backend" / "round_runner.py").read_text(encoding="utf-8")
    check("shutil.rmtree(child, ignore_errors=True)" in rr_src, "fresh mode wipes local challenge dirs")

    # include-solved must neutralise the "skip solved" switch instead of deadlocking.
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "challenges"
        (base / "old-task").mkdir(parents=True)
        (base / "old-task" / "flag.txt").write_text("flag{stale}", encoding="utf-8")
        (base / "another").mkdir()
        (base / "keep.txt").write_text("not a dir", encoding="utf-8")
        wiped = round_runner._wipe_challenge_dirs(str(base))
        check(wiped == 2, "fresh mode wipes the pulled challenge dirs")
        check(not (base / "old-task").exists(), "stale solve dir is gone")
        check((base / "keep.txt").exists(), "loose files are left alone")
        check(round_runner._wipe_challenge_dirs(str(Path(tmp) / "missing")) == 0, "missing dir is a no-op")

    rr_src2 = (Path(__file__).resolve().parents[1] / "backend" / "round_runner.py").read_text(encoding="utf-8")
    check("skip_solved = False" in rr_src2, "include-solved disables the skip switch")

    print(f"\nALL FRESH-SOLVE CHECKS PASSED ({OK} checks)")


if __name__ == "__main__":
    asyncio.run(asyncio.sleep(0))
    main()
