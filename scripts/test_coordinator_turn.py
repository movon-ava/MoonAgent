"""Smoke-test the DeepSeek coordinator agent (one turn, fake CTFd, no Docker)."""

import asyncio

from pydantic_ai import Agent
from pydantic_ai.messages import ToolCallPart

from backend.agents.claude_coordinator import COORDINATOR_PROMPT
from backend.agents.deepseek_coordinator import _build_toolset
from backend.config import Settings
from backend.cost_tracker import CostTracker
from backend.deps import CoordinatorDeps
from backend.models import resolve_model, resolve_model_settings


class FakeCTFd:
    async def fetch_all_challenges(self):
        return [
            {
                "name": "warmup",
                "category": "misc",
                "value": 10,
                "solves": 3,
                "description": "A trivial check: the flag is hidden in plain sight.",
            }
        ]

    async def fetch_solved_names(self):
        return set()


async def main() -> None:
    settings = Settings()
    spec = "deepseek/deepseek-flash/low"
    deps = CoordinatorDeps(
        ctfd=FakeCTFd(),
        cost_tracker=CostTracker(),
        settings=settings,
        model_specs=[spec],
        challenges_root="challenges",
        no_submit=True,
    )
    agent: Agent[None, str] = Agent(
        resolve_model(spec, settings),
        toolsets=[_build_toolset(deps)],
        system_prompt=COORDINATOR_PROMPT,
        model_settings=resolve_model_settings(spec),
    )
    result = await agent.run(
        "A challenge named 'warmup' is unsolved. Call fetch_challenges first, "
        "then reply with one sentence on what you would do next."
    )
    called = [
        part.tool_name
        for msg in result.all_messages()
        for part in getattr(msg, "parts", [])
        if isinstance(part, ToolCallPart)
    ]
    print("tools called:", called)
    print("output:", (result.output or "").strip()[:300])
    print("usage:", result.usage)


asyncio.run(main())
