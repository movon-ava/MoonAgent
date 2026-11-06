"""Check that trace files never keep raw flags or credentials.

Run with:  uv run python scripts/test_trace_mask.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.tracing import SolverTracer, mask_secrets  # noqa: E402

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
SK = "sk-test-0123456789abcdefghijkl"
AK = "ak_live_example_key_0001"
FLAG = "flag{deepseek_sandbox_ok_42}"


def check_mask_function() -> None:
    secret = f"key={SK} jwt={JWT} ak={AK} SessionStore=abc123def456ghi789 flag={{1}}"
    masked = mask_secrets(secret)
    assert SK not in masked, masked
    assert JWT not in masked, masked
    assert AK not in masked, masked
    assert "SessionStore=<token>" in masked, masked
    assert "sk-<api" not in masked  # sanity: pattern not mangled
    print("mask function ok")

    for raw in (FLAG, "DASCTF{abc123def456}", "moectf{中文flag内容}"):
        out = mask_secrets(raw)
        assert raw not in out, (raw, out)
        assert out.endswith("}") and "{" in out, out
    assert mask_secrets("no secrets here") == "no secrets here"
    assert mask_secrets("") == ""
    print("flag masking ok")


def check_tracer(tmp: Path) -> None:
    tracer = SolverTracer("mask-demo", "deepseek/deepseek-flash", log_dir=str(tmp))
    tracer.tool_call("bash", {"command": f"cat .env  # {SK}"}, step=1)
    tracer.tool_result("bash", f"FLAG={FLAG}\nSESSION={JWT}", step=1)
    tracer.event("note", flag=FLAG, nested={"token": AK}, items=[FLAG])
    tracer.usage(10, 5, 0, 0.0001)
    tracer.close()

    text = Path(tracer.path).read_text(encoding="utf-8")
    for secret in (SK, JWT, AK, "deepseek_sandbox_ok_42"):
        assert secret not in text, f"{secret!r} leaked into the trace"
    events = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "note", "usage"], events
    assert events[0]["step"] == 1
    assert events[3]["cost_usd"] > 0, "numbers must survive masking"
    assert events[2]["items"][0] != FLAG and events[2]["nested"]["token"] != AK
    print("tracer masking ok")
    print("trace lines:", len(events))


def check_opt_out(tmp: Path) -> None:
    tracer = SolverTracer("mask-off", "deepseek/deepseek-flash", log_dir=str(tmp), mask=False)
    tracer.tool_result("bash", FLAG, step=1)
    tracer.close()
    text = Path(tracer.path).read_text(encoding="utf-8")
    assert FLAG in text, "mask=False must keep the raw text"
    print("opt-out ok")


def main() -> int:
    check_mask_function()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        check_tracer(tmp)
        check_opt_out(tmp)
    print("ALL TRACE-MASK CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
