"""Verify the project's DeepSeek integration end to end (no Docker needed)."""

import asyncio
import os

from pydantic_ai import Agent

from backend.config import Settings
from backend.cost_tracker import calc_cost
from backend.models import (
    context_window,
    default_model_specs,
    resolve_model,
    resolve_model_settings,
    supports_vision,
)
from backend.output_types import FlagFound


async def main() -> None:
    print("NO_PROXY after backend import:", os.environ.get("NO_PROXY"))
    settings = Settings()
    print("default_models:", default_model_specs(settings))
    print("deepseek key set:", bool(settings.deepseek_api_key), "base:", settings.deepseek_base_url)

    spec = "deepseek/deepseek-flash/low"
    model = resolve_model(spec, settings)
    model_settings = resolve_model_settings(spec)
    print("model:", type(model).__name__, "| settings:", model_settings)
    print("vision:", supports_vision("deepseek/deepseek-flash"), "| ctx:", context_window("deepseek/deepseek-flash"))

    agent = Agent(model, system_prompt="Be terse.", model_settings=model_settings)
    r = await agent.run("Reply with exactly: PONG")
    print("1) plain:", repr(r.output), "| usage:", r.usage())

    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    tool_agent = Agent(model, tools=[add], model_settings=model_settings)
    r2 = await tool_agent.run("Use the add tool for 17+25, then report only the number.")
    print("2) tool:", repr(r2.output))

    solver_agent = Agent(model, output_type=FlagFound, model_settings=model_settings)
    r3 = await solver_agent.run("The flag is flag{proj_ok}. Report it.")
    print("3) structured:", r3.output)
    usage = r3.usage()
    print("4) cost:", calc_cost(usage, "deepseek-flash", "deepseek"), "| tokens in/out:", usage.input_tokens, usage.output_tokens)

    # Coordinator wiring (imports + toolset construction only; no CTFd calls)
    from backend.agents.coordinator_loop import build_deps
    from backend.agents.deepseek_coordinator import _build_toolset, _coordinator_spec

    ctfd, cost_tracker, deps = build_deps(settings, ["deepseek/deepseek-flash"], "challenges", True)
    toolset = _build_toolset(deps)
    print("5) coordinator spec:", _coordinator_spec(None), "| tools:", sorted(toolset.tools.keys()))
    print("6) coordinator model settings:", resolve_model_settings("deepseek/deepseek-flash"))
    await ctfd.close()


asyncio.run(main())
