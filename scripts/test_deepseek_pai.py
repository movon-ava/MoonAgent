"""End-to-end pydantic-ai test against DeepSeek (tools, structured output, history, cost)."""
import asyncio
import os
import time

# httpx cannot parse IPv6 entries in NO_PROXY (InvalidURL: Invalid port: ':1]')
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel, OpenAIModelSettings
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

KEY = os.environ.get("DEEPSEEK_API_KEY") or ""


class FlagFound(BaseModel):
    flag: str | None = None
    reasoning: str = ""


def make_model(name="deepseek-flash", **profile_kwargs):
    profile = OpenAIModelProfile(
        supports_tools=True,
        supports_thinking=True,
        openai_chat_thinking_field="reasoning_content",
        openai_chat_send_back_thinking_parts=False,
        openai_supports_tool_choice_required=False,
        supports_json_schema_output=False,
        openai_supports_strict_tool_definition=False,
        **profile_kwargs,
    )
    return OpenAIModel(
        name,
        provider=OpenAIProvider(base_url="https://api.deepseek.com", api_key=KEY),
        profile=profile,
    )


async def main():
    model = make_model()
    settings = OpenAIModelSettings(max_tokens=8000, openai_reasoning_effort="low", timeout=180)

    # 1) plain
    a = Agent(model, system_prompt="Be terse.", model_settings=settings)
    t0 = time.time()
    r = await a.run("Reply with exactly: OK")
    print("1) plain:", r.output, f"({time.time()-t0:.1f}s, usage={r.usage().input_tokens}/{r.usage().output_tokens})")

    # 2) tool call loop
    calls = []

    def get_hint(topic: str) -> str:
        """Return a hint for the given topic."""
        calls.append(topic)
        return "the answer is 42"

    b = Agent(model, system_prompt="Be terse. Use tools when asked.", tools=[get_hint], model_settings=settings)
    r2 = await b.run("Call get_hint for 'life', then tell me the answer word.")
    print("2) tools:", repr(r2.output), "calls=", calls)

    # 3) structured output
    c = Agent(model, system_prompt="You are a CTF agent. When done, call the output tool.", output_type=FlagFound, model_settings=settings)
    r3 = await c.run("The flag is flag{test_123}. Report it.")
    print("3) structured:", r3.output)

    # 4) history reuse
    h = r3.all_messages()
    r4 = await c.run("Now report it again, same flag.", message_history=h)
    print("4) history:", r4.output, "msgs=", len(r4.all_messages()))

    # 5) big max_tokens
    big = OpenAIModelSettings(max_tokens=32000, timeout=180)
    d = Agent(model, model_settings=big)
    r5 = await d.run("Write the word PONG exactly once.")
    print("5) big max_tokens:", repr(r5.output))

    # 6) cost calc
    try:
        from genai_prices import calc_price

        for mid in ("deepseek-flash", "deepseek-v4-pro", "deepseek-chat"):
            u = r.usage()
            try:
                price = calc_price(u, mid, provider_id="deepseek")
                print(f"6) price {mid}: {price}")
            except Exception as e:  # noqa: BLE001
                print(f"6) price {mid}: ERR {e}")
    except Exception as e:  # noqa: BLE001
        print("6) genai_prices import fail:", e)


asyncio.run(main())
