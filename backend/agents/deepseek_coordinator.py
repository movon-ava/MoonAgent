"""Pydantic AI coordinator — drives the shared event loop with any Pydantic AI model.

Used for DeepSeek: the upstream Claude/Codex SDK coordinators only accept their
own model names, while DeepSeek is reachable through the OpenAI-compatible
Pydantic AI provider. Tool logic is shared with the other backends via
``backend.agents.coordinator_core``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import UsageLimits

from backend.agents.claude_coordinator import COORDINATOR_PROMPT
from backend.agents.coordinator_core import (
    do_spawn_batch,
    do_broadcast,
    do_bump_agent,
    do_check_swarm_status,
    do_fetch_challenges,
    do_get_solve_status,
    do_kill_swarm,
    do_read_solver_trace,
    do_spawn_swarm,
    do_submit_flag,
)
from backend.agents.coordinator_loop import build_deps, run_event_loop
from backend.config import Settings
from backend.deps import CoordinatorDeps
from backend.models import model_id_from_spec, resolve_model, resolve_model_settings
from backend.tracing import SolverTracer

logger = logging.getLogger(__name__)


def _build_toolset(deps: CoordinatorDeps) -> FunctionToolset:
    """Thin Pydantic AI wrappers around the shared coordinator_core tools."""
    toolset: FunctionToolset = FunctionToolset(max_retries=2)

    @toolset.tool
    async def fetch_challenges() -> str:
        """List all challenges with category, points, solve count, and status."""
        return await do_fetch_challenges(deps)

    @toolset.tool
    async def get_solve_status() -> str:
        """Check which challenges are solved and which swarms are running."""
        return await do_get_solve_status(deps)

    @toolset.tool
    async def spawn_swarm(challenge_name: str) -> str:
        """Launch all solver models on a challenge."""
        return await do_spawn_swarm(deps, challenge_name)

    @toolset.tool
    async def spawn_batch(count: int = 5) -> str:
        """Spawn the next batch of challenges from one direction (drill mode).

        Use this instead of many spawn_swarm calls while drill mode is on: each
        call returns one category's batch and advances to the next category.
        """
        return await do_spawn_batch(deps, count)

    @toolset.tool
    async def check_swarm_status(challenge_name: str) -> str:
        """Get per-agent progress for a swarm."""
        return await do_check_swarm_status(deps, challenge_name)

    @toolset.tool
    async def submit_flag(challenge_name: str, flag: str) -> str:
        """Submit a flag to CTFd."""
        return await do_submit_flag(deps, challenge_name, flag)

    @toolset.tool
    async def kill_swarm(challenge_name: str) -> str:
        """Cancel all agents for a challenge. Only allowed after a confirmed flag."""
        return await do_kill_swarm(deps, challenge_name)

    @toolset.tool
    async def bump_agent(challenge_name: str, model_spec: str, insights: str) -> str:
        """Send targeted insights to a stuck agent."""
        return await do_bump_agent(deps, challenge_name, model_spec, insights)

    @toolset.tool
    async def broadcast(challenge_name: str, message: str) -> str:
        """Broadcast a strategic hint to ALL solvers on a challenge."""
        return await do_broadcast(deps, challenge_name, message)

    @toolset.tool
    async def read_solver_trace(challenge_name: str, model_spec: str, last_n: int = 20) -> str:
        """Read recent trace events from a specific solver to see what it tried and where it is stuck."""
        return await do_read_solver_trace(deps, challenge_name, model_spec, last_n)

    return toolset


def _coordinator_spec(coordinator_model: str | None) -> str:
    """Normalize --coordinator-model to a provider spec ('deepseek-flash' → 'deepseek/deepseek-flash')."""
    if not coordinator_model:
        return "deepseek/deepseek-flash"
    return coordinator_model if "/" in coordinator_model else f"deepseek/{coordinator_model}"


async def run_deepseek_coordinator(
    settings: Settings,
    model_specs: list[str] | None = None,
    challenges_root: str = "challenges",
    no_submit: bool = False,
    coordinator_model: str | None = None,
    msg_port: int = 0,
) -> dict[str, Any]:
    """Run the Pydantic AI coordinator with the shared event loop."""
    ctfd, cost_tracker, deps = build_deps(settings, model_specs, challenges_root, no_submit)
    deps.msg_port = msg_port

    spec = _coordinator_spec(coordinator_model)
    model_id = model_id_from_spec(spec)
    agent: Agent[None, str] = Agent(
        resolve_model(spec, settings),
        toolsets=[_build_toolset(deps)],
        system_prompt=COORDINATOR_PROMPT,
        model_settings=resolve_model_settings(spec),
    )
    history: list[Any] = []
    # Without a trace file the dashboard shows "0 solver" while the coordinator
    # is thinking and fetching lists, which looks like nothing is happening.
    tracer = SolverTracer("coordinator", model_id)
    tracer.event("start", challenge="coordinator", model=model_id, category="coordinator", value=0)

    async def turn_fn(msg: str) -> None:
        nonlocal history
        t0 = time.monotonic()
        try:
            result = await agent.run(
                msg,
                message_history=history or None,
                usage_limits=UsageLimits(request_limit=None),
            )
        except Exception as e:  # keep the event loop alive across API hiccups
            logger.error("Coordinator turn failed: %s", e, exc_info=True)
            tracer.event("message", text=f"coordinator turn failed: {e}")
            return

        duration = time.monotonic() - t0
        usage = result.usage
        cost_tracker.record(
            "coordinator", usage, model_id,
            provider_spec="deepseek", duration_seconds=duration,
        )
        history = result.all_messages()
        logger.info(
            "Coordinator turn done (%.1fs, %d in / %d out, %d messages)",
            duration, usage.input_tokens, usage.output_tokens, len(history),
        )
        if (result.output or "").strip():
            tracer.message(result.output)
        tracer.event(
            "usage",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            duration_seconds=round(duration, 1),
        )
        if not (result.output or "").strip():
            logger.debug("Coordinator turn had no text output (tool-only turn)")

    logger.info("DeepSeek coordinator: model=%s solvers=%s", spec, deps.model_specs)
    try:
        return await run_event_loop(deps, ctfd, cost_tracker, turn_fn)
    finally:
        tracer.event("finish", status="done")
        tracer.close()
