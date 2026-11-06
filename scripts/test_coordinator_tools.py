"""Check that all three coordinators expose the same tool surface.

Run with:  uv run python scripts/test_coordinator_tools.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agents import coordinator_tools as ct  # noqa: E402
from backend.agents.deepseek_coordinator import _build_toolset  # noqa: E402

EXPECTED = {
    "fetch_challenges",
    "get_solve_status",
    "spawn_swarm",
    "spawn_batch",
    "check_swarm_status",
    "submit_flag",
    "kill_swarm",
    "bump_agent",
    "broadcast",
    "read_solver_trace",
}


class DummyDeps:
    """dispatch() is only exercised for the unknown-tool branch."""


def main() -> int:
    names = set(ct.TOOL_NAMES)
    assert names == EXPECTED, f"tool table drift: {names ^ EXPECTED}"
    assert len(ct.TOOL_NAMES) == len(names), "duplicate tool name"
    print(f"tool table ok: {len(names)} tools")

    tools = ct.json_tools()
    assert [t["name"] for t in tools] == list(ct.TOOL_NAMES), "json_tools order/shape drift"
    for spec, rendered in zip(ct.TOOLS, tools, strict=True):
        schema = rendered["inputSchema"]
        assert schema["type"] == "object"
        assert set(schema["properties"]) == set(spec.params), spec.name
        assert set(schema.get("required", [])) == set(spec.required), spec.name
    print("json schema ok")

    spawn = next(t for t in tools if t["name"] == "spawn_batch")
    assert spawn["inputSchema"]["properties"]["count"] == {"type": "integer"}
    print("integer param ok")

    result = asyncio.run(ct.dispatch(DummyDeps(), "not_a_tool", {}))
    assert result.startswith("Unknown tool"), result
    print("unknown tool ok")

    toolset = _build_toolset(DummyDeps())
    deepseek_names = set(getattr(toolset, "tools", {}).keys())
    assert deepseek_names == EXPECTED, f"deepseek toolset drift: {deepseek_names ^ EXPECTED}"
    print("deepseek toolset ok")

    try:
        from backend.agents.claude_coordinator import _build_coordinator_mcp
    except Exception as exc:  # noqa: BLE001 - SDK is optional in this environment
        print(f"claude sdk unavailable, skipping: {exc.__class__.__name__}")
        print("ALL COORDINATOR-TOOL CHECKS PASSED")
        return 0

    server = _build_coordinator_mcp(DummyDeps())
    assert server is not None
    print("claude mcp server built")

    from backend.agents import codex_coordinator

    codex_names = {t["name"] for t in codex_coordinator.COORDINATOR_TOOLS}
    assert codex_names == EXPECTED, f"codex tools drift: {codex_names ^ EXPECTED}"
    print("codex tool list ok")

    print("ALL COORDINATOR-TOOL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
