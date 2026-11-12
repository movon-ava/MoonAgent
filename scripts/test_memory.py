"""Checks for the per-challenge memory notebook and its prompt wiring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import memory
from backend.prompts import ChallengeMeta, build_prompt


def main() -> None:
    name = "_test_memory_demo"
    memory.clear(name)
    assert memory.digest(name) == ""

    memory.note(name, "note", "服务是 nc，先发 magic 'AB' 再发长度")
    memory.note(name, "rejected", "flag{guess}")
    memory.note(name, "flag", "flag{real}")
    text = memory.digest(name)
    assert "magic" in text and "flag{guess}" in text and "flag{real}" in text
    print("notes ok")

    # Whitespace is collapsed and long notes are clipped.
    memory.note(name, "note", "a" * 5000)
    long_line = [ln for ln in memory.digest(name, 9000).splitlines() if ln.startswith("- [") and "aaaa" in ln]
    assert long_line and len(long_line[-1]) < 1200
    print("clip ok")

    prompt = build_prompt(ChallengeMeta(name=name), [], prior_notes=text)
    assert "队友之前的分析" in prompt and "flag{real}" in prompt
    assert "队友之前的分析" not in build_prompt(ChallengeMeta(name=name), [])
    print("prompt ok")

    # The notebook is trimmed instead of growing forever.
    for i in range(60):
        memory.note(name, "note", f"note {i} " + "x" * 400)
    size = memory.path_for(name).stat().st_size
    assert size <= memory.MAX_FILE_CHARS + 200, size
    assert "note 59" in memory.digest(name, 12000)
    print("trim ok")


    # Transient environment failures must never be cached as challenge insight.
    from backend.agents.solver import _is_transient_failure

    assert _is_transient_failure("Error: Connection error."), "connection error cached as a finding"
    assert _is_transient_failure("Error: 504 Gateway Time-out"), "gateway error cached as a finding"
    assert not _is_transient_failure("inputs 16 bytes, magic is 'AB' at offset 4"), "real finding dropped"
    print("transient ok")
    memory.clear(name)
    assert not memory.path_for(name).exists()
    print("ALL MEMORY CHECKS PASSED")


if __name__ == "__main__":
    main()
