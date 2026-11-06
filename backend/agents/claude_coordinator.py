"""Claude Agent SDK coordinator — uses the shared event loop with a Claude SDK client."""

from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    create_sdk_mcp_server,
    tool,
)

from backend.agents.coordinator_loop import build_deps, run_event_loop
from backend.agents.coordinator_tools import TOOLS, ToolSpec, dispatch, py_params
from backend.config import Settings
from backend.deps import CoordinatorDeps

logger = logging.getLogger(__name__)

COORDINATOR_PROMPT = """\
You are a CTF competition coordinator running for the ENTIRE duration of a live competition.
Your job is to maximize the number of challenges solved.

Strategy:
- Spawn swarms for unsolved challenges, prioritizing by solve count (easy first)
- Dispatch in your FIRST turn: call fetch_challenges once, then spawn immediately.
  Do not re-read the catalog between spawns (the list is cached; re-reading only
  burns turns while solvers sit idle).
- Use read_solver_trace to monitor what each solver is doing and where it's stuck
- When agents are stuck, read their traces, then craft targeted bumps with specific technical guidance
- Use broadcast to share cross-solver insights (e.g. flag format discovery, shared vulnerabilities)

CRITICAL RULES:
- NEVER kill a swarm. Solvers will keep trying indefinitely with different approaches.
  Even when stuck, they often unstick themselves after several bumps. Your job is to
  HELP them, not give up on them. The only time a swarm should die is when the flag
  is confirmed correct.
- When a solver seems stuck, bump it with very specific technical guidance based on
  its trace. Tell it exactly what to try next — specific tools, techniques, approaches.
- Cost is not a concern. Keep all swarms running.
- Drill mode: when the challenge list is large, prefer spawn_batch(count) - it
  dispatches one direction (misc, then re, then crypto, ...) at a time and
  rotates automatically. Call it again for the next direction once a batch is done.
- Practice mode: when fetch_challenges reports `"include_solved": true`, solved
  challenges are spawnable too (`"spawnable": true`) - the operator asked to run
  them again. Do not stop with "nothing to spawn" while any spawnable entry
  remains. Their submissions return ALREADY SOLVED, which still counts as done.

You will receive event messages. Respond with tool calls to manage the competition.
"""


def _text(s: str) -> dict:
    """Wrap a string in the Claude SDK MCP tool return format."""
    return {"content": [{"type": "text", "text": s}]}


def _build_coordinator_mcp(deps: CoordinatorDeps):
    """MCP server exposing the shared coordinator tool surface."""

    def _handler(spec: ToolSpec):
        async def call(args: dict) -> dict:
            return _text(await dispatch(deps, spec.name, args or {}))

        return call

    tools = [
        tool(spec.name, spec.description, py_params(spec))(_handler(spec)) for spec in TOOLS
    ]
    # spawn_batch used to be missing here even though the other coordinators had
    # it; rendering the list from TOOLS keeps the three stacks in sync.
    return create_sdk_mcp_server(name="coordinator", version="1.0.0", tools=tools)


async def run_claude_coordinator(
    settings: Settings,
    model_specs: list[str] | None = None,
    challenges_root: str = "challenges",
    no_submit: bool = False,
    coordinator_model: str | None = None,
    msg_port: int = 0,
) -> dict[str, Any]:
    """Run the Claude Agent SDK coordinator with the shared event loop."""
    ctfd, cost_tracker, deps = build_deps(
        settings, model_specs, challenges_root, no_submit,
    )
    deps.msg_port = msg_port

    mcp_server = _build_coordinator_mcp(deps)
    resolved_model = coordinator_model or "claude-opus-4-6"

    allowed = {
        "mcp__coordinator__fetch_challenges", "mcp__coordinator__get_solve_status",
        "mcp__coordinator__spawn_swarm", "mcp__coordinator__check_swarm_status",
        "mcp__coordinator__submit_flag", "mcp__coordinator__kill_swarm",
        "mcp__coordinator__bump_agent", "mcp__coordinator__broadcast",
        "mcp__coordinator__read_solver_trace",
        "ToolSearch",
        "TaskCreate", "TaskUpdate", "TaskGet", "TaskList", "TaskOutput", "TaskStop",
    }

    async def enforce_allowlist(input_data, tool_use_id, context):
        if input_data.get("hook_event_name") != "PreToolUse":
            return {}
        tool = input_data.get("tool_name", "")
        if tool in allowed:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"{tool} not available to coordinator.",
            }
        }

    options = ClaudeAgentOptions(
        model=resolved_model,
        system_prompt=COORDINATOR_PROMPT,
        env={"CLAUDECODE": ""},
        mcp_servers={"coordinator": mcp_server},
        allowed_tools=list(allowed),
        permission_mode="bypassPermissions",
        hooks={
            "PreToolUse": [HookMatcher(hooks=[enforce_allowlist])],
        },
    )

    async with ClaudeSDKClient(options=options) as client:
        async def turn_fn(msg: str) -> None:
            logger.debug(f"Coordinator query: {msg[:200]}")
            await client.query(msg)
            msg_count = 0
            async for message in client.receive_response():
                msg_count += 1
                msg_type = type(message).__name__
                logger.debug(f"Coordinator received: {msg_type}")
                if isinstance(message, ResultMessage):
                    cost = getattr(message, "total_cost_usd", 0)
                    session = getattr(message, "session_id", None)
                    logger.info(f"Claude coordinator turn done (messages={msg_count}, cost=${cost:.4f}, session={session})")
            if msg_count == 0:
                logger.warning("Coordinator turn produced no messages!")

        return await run_event_loop(deps, ctfd, cost_tracker, turn_fn)
