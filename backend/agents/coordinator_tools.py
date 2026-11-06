"""Single source of truth for the coordinator tool surface.

Three coordinators drive the same competition loop through different agent
stacks (pydantic-ai, the Claude Agent SDK, and the Codex app-server).  Each one
used to spell out the tool list — names, descriptions, JSON schemas and the
name → handler dispatch — separately, which is how the codex side ended up
missing ``spawn_batch`` for a while.

``TOOLS`` describes the surface once; ``json_tools()`` renders it for the
Codex app-server and ``dispatch()`` executes a call for any adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.agents import coordinator_core as core
from backend.deps import CoordinatorDeps

# JSON-schema type → Python type, used when registering with the Claude SDK.
PY_TYPES: dict[str, type] = {"string": str, "integer": int}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    # parameter name → JSON-schema type; empty dict means "no arguments"
    params: dict[str, str] = field(default_factory=dict)
    required: tuple[str, ...] = ()

    def input_schema(self) -> dict[str, Any]:
        properties = {name: {"type": kind} for name, kind in self.params.items()}
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if self.required:
            schema["required"] = list(self.required)
        return schema


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "fetch_challenges",
        "List all challenges with category, points, solve count, and status.",
    ),
    ToolSpec(
        "get_solve_status",
        "Check which challenges are solved and which swarms are running.",
    ),
    ToolSpec(
        "spawn_swarm",
        "Launch all solver models on a challenge.",
        {"challenge_name": "string"},
        ("challenge_name",),
    ),
    ToolSpec(
        "spawn_batch",
        "Spawn the next batch of challenges from one direction (drill mode).",
        {"count": "integer"},
    ),
    ToolSpec(
        "check_swarm_status",
        "Get per-agent progress for a swarm.",
        {"challenge_name": "string"},
        ("challenge_name",),
    ),
    ToolSpec(
        "submit_flag",
        "Submit a flag to the platform.",
        {"challenge_name": "string", "flag": "string"},
        ("challenge_name", "flag"),
    ),
    ToolSpec(
        "kill_swarm",
        "Cancel all agents for a challenge.",
        {"challenge_name": "string"},
        ("challenge_name",),
    ),
    ToolSpec(
        "bump_agent",
        "Send targeted insights to a stuck agent.",
        {"challenge_name": "string", "model_spec": "string", "insights": "string"},
        ("challenge_name", "model_spec", "insights"),
    ),
    ToolSpec(
        "broadcast",
        "Broadcast a strategic hint to ALL solvers on a challenge.",
        {"challenge_name": "string", "message": "string"},
        ("challenge_name", "message"),
    ),
    ToolSpec(
        "read_solver_trace",
        "Read recent trace events from a specific solver.",
        {"challenge_name": "string", "model_spec": "string", "last_n": "integer"},
        ("challenge_name", "model_spec"),
    ),
)

TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in TOOLS)


def json_tools() -> list[dict[str, Any]]:
    """The tool list in the shape the Codex app-server expects."""
    return [
        {"name": spec.name, "description": spec.description, "inputSchema": spec.input_schema()}
        for spec in TOOLS
    ]


def py_params(spec: ToolSpec) -> dict[str, type]:
    """The tool's parameters in the shape the Claude SDK ``tool()`` expects."""
    return {name: PY_TYPES[kind] for name, kind in spec.params.items()}


async def dispatch(deps: CoordinatorDeps, name: str, args: dict[str, Any] | None = None) -> str:
    """Run one coordinator tool call.  Unknown names return a readable error."""
    a = args or {}
    if name == "fetch_challenges":
        return await core.do_fetch_challenges(deps)
    if name == "get_solve_status":
        return await core.do_get_solve_status(deps)
    if name == "spawn_swarm":
        return await core.do_spawn_swarm(deps, a["challenge_name"])
    if name == "spawn_batch":
        return await core.do_spawn_batch(deps, int(a.get("count") or 5))
    if name == "check_swarm_status":
        return await core.do_check_swarm_status(deps, a["challenge_name"])
    if name == "submit_flag":
        return await core.do_submit_flag(deps, a["challenge_name"], a["flag"])
    if name == "kill_swarm":
        return await core.do_kill_swarm(deps, a["challenge_name"])
    if name == "bump_agent":
        return await core.do_bump_agent(
            deps, a["challenge_name"], a["model_spec"], a["insights"]
        )
    if name == "broadcast":
        return await core.do_broadcast(deps, a["challenge_name"], a["message"])
    if name == "read_solver_trace":
        return await core.do_read_solver_trace(
            deps, a["challenge_name"], a["model_spec"], int(a.get("last_n") or 20)
        )
    return f"Unknown tool: {name}"
