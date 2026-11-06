"""Scratch probe: what does pydantic-ai's event stream handler give us per step?"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

from pydantic_ai import Agent, RunContext  # noqa: E402
from pydantic_ai.messages import (  # noqa: E402
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)

from backend.config import Settings  # noqa: E402
from backend.models import resolve_model, resolve_model_settings  # noqa: E402


async def handler(ctx: RunContext[None], events) -> None:
    async for ev in events:
        kind = type(ev).__name__
        if isinstance(ev, PartStartEvent):
            print(f"[start] part={type(ev.part).__name__}")
        elif isinstance(ev, PartDeltaEvent):
            d = ev.delta
            if isinstance(d, ThinkingPartDelta) and d.content_delta:
                print(f"[think] {d.content_delta[:60]!r}")
            elif isinstance(d, TextPartDelta) and d.content_delta:
                print(f"[text] {d.content_delta[:60]!r}")
        elif isinstance(ev, FunctionToolCallEvent):
            print(f"[tool] {ev.part.tool_name} {str(ev.part.args)[:80]}")
        elif isinstance(ev, FunctionToolResultEvent):
            part = ev.part
            print(f"[result] {getattr(part, 'tool_name', '?')} {str(getattr(part, 'content', ev.content))[:80]!r}")
        else:
            print(f"[{kind}]")


async def main() -> None:
    settings = Settings()
    model = resolve_model("deepseek/deepseek-flash", settings)
    agent = Agent(model, system_prompt="Be terse.")

    @agent.tool
    async def add(ctx: RunContext[None], a: int, b: int) -> int:
        return a + b

    r = await agent.run(
        "A farmer has 17 sheep; all but 9 run away. How many remain? "
        "Reason carefully about the wording first, then answer. Use the add tool "
        "to compute 4+5 as a sanity check.",
        event_stream_handler=handler,
    )
    print("OUTPUT:", r.output)
    for msg in r.new_messages():
        print("MSG:", type(msg).__name__, [type(p).__name__ for p in getattr(msg, "parts", [])])


asyncio.run(main())
