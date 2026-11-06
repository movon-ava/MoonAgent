import inspect
import typing

import pydantic_ai
from pydantic_ai.models.openai import OpenAIModel, OpenAIModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

print("pydantic_ai", pydantic_ai.__version__)
print("OpenAIModelSettings keys:", sorted(typing.get_type_hints(OpenAIModelSettings)))
print()
print("OpenAIModel.__init__:", inspect.signature(OpenAIModel.__init__))
print()
print("OpenAIProvider.__init__:", inspect.signature(OpenAIProvider.__init__))
print()

import pydantic_ai.profiles as profiles

print("profiles module:", [n for n in dir(profiles) if not n.startswith("_")])
try:
    from pydantic_ai.profiles.openai import OpenAIModelProfile
    print("OpenAIModelProfile keys:", sorted(typing.get_type_hints(OpenAIModelProfile)))
except Exception as e:  # noqa: BLE001
    print("no OpenAIModelProfile:", e)

for mod in ("genai_prices",):
    try:
        m = __import__(mod)
        print(mod, getattr(m, "__version__", "?"), dir(m)[:20])
    except Exception as e:  # noqa: BLE001
        print(mod, "missing", e)
