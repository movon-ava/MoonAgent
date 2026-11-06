"""Probe DeepSeek API surfaces: OpenAI-compatible, Anthropic-compatible, tools, vision, models list."""
import json
import os
import urllib.error
import urllib.request

KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not KEY:
    raise SystemExit("set DEEPSEEK_API_KEY")
BASE = "https://api.deepseek.com"


def post(path, payload, headers=None, timeout=120):
    url = BASE + path
    hdrs = {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return e.code, body
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)


def show(title, res, limit=1200):
    print(f"\n=== {title} ===")
    status, data = res
    print("status:", status)
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    print(text[:limit])


# 1) OpenAI chat completions
show("openai chat deepseek-flash", post("/chat/completions", {
    "model": "deepseek-flash",
    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    "max_tokens": 20,
}))

# 2) legacy alias
show("openai chat deepseek-chat alias", post("/chat/completions", {
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    "max_tokens": 20,
}))

# 3) Anthropic messages endpoint (bearer + x-api-key variants)
show("anthropic messages (x-api-key)", post("/anthropic/v1/messages", {
    "model": "deepseek-flash", "max_tokens": 20,
    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
}, headers={"x-api-key": KEY, "anthropic-version": "2023-06-01"})[0:2])

show("anthropic messages (bearer)", post("/anthropic/v1/messages", {
    "model": "deepseek-v4-pro", "max_tokens": 20,
    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
}, headers={"anthropic-version": "2023-06-01"}))

# 4) tool calling (openai)
tools = [{
    "type": "function",
    "function": {
        "name": "get_flag",
        "description": "Return the flag for a challenge",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
}]
show("openai tool call", post("/chat/completions", {
    "model": "deepseek-flash",
    "messages": [{"role": "user", "content": "Use the get_flag tool for challenge 'web1'."}],
    "tools": tools,
    "max_tokens": 200,
}))

# 5) vision input
show("openai vision (deepseek-flash)", post("/chat/completions", {
    "model": "deepseek-flash",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "What color is this image? One word."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="}},
    ]}],
    "max_tokens": 50,
}))

# 6) reasoning_effort + responses api?
show("openai reasoning_effort high", post("/chat/completions", {
    "model": "deepseek-flash",
    "messages": [{"role": "user", "content": "1+1=?"}],
    "max_tokens": 50,
    "reasoning_effort": "high",
}))

show("openai /responses", post("/responses", {
    "model": "deepseek-flash", "input": "Reply with exactly: OK", "max_output_tokens": 20,
}))
