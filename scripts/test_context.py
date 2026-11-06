"""Checks for context compaction / rollback (P3)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)

from backend.agents.solver import Solver


def _stub(messages, limit=1000):
    events = []
    stub = SimpleNamespace(
        _messages=messages,
        settings=SimpleNamespace(context_limit_chars=limit),
        agent_name="test",
        tracer=SimpleNamespace(event=lambda *a, **k: events.append((a, k))),
    )
    stub._context_chars = lambda: Solver._context_chars(stub)
    stub._compact_history = lambda: Solver._compact_history(stub)
    return stub, events


def main() -> None:
    big = "x" * 4000
    messages = [
        ModelRequest(parts=[ToolReturnPart(tool_name="bash", content=big, tool_call_id="1")]),
        ModelResponse(parts=[ThinkingPart(content="y" * 4000)]),
        ModelResponse(parts=[ToolCallPart(tool_name="bash", args="z" * 3000, tool_call_id="2")]),
        ModelResponse(parts=[TextPart(content="w" * 4000)]),
    ]
    # Pad with recent turns that must stay untouched.
    messages += [ModelResponse(parts=[TextPart(content="tail")]) for _ in range(9)]

    stub, events = _stub(list(messages))
    before = stub._context_chars()
    stub._compact_history()
    after = stub._context_chars()
    assert before > 1000 and after < before, (before, after)
    assert any(a[0] and a[0][0] == "context_compacted" for a in events), events
    assert stub._messages[-1].parts[0].content == "tail", "recent turns must survive"
    print(f"compact ok: {before} -> {after}")

    # Rollback keeps head and tail, drops the middle.
    msgs = [ModelResponse(parts=[TextPart(content=f"m{i}")]) for i in range(20)]
    stub2, events2 = _stub(msgs)
    stub2._messages = msgs
    Solver._rollback_history(stub2)
    assert len(stub2._messages) == 6, len(stub2._messages)
    assert stub2._messages[0].parts[0].content == "m0"
    assert stub2._messages[-1].parts[0].content == "m19"
    print("rollback ok")

    # Under the limit nothing changes.
    stub3, _ = _stub([ModelResponse(parts=[TextPart(content="short")])], limit=10_000)
    assert stub3._compact_history() == 0
    print("no-op ok")

    print("ALL CONTEXT-SURGERY CHECKS PASSED")


if __name__ == "__main__":
    main()
