"""Probe DeepSeek thinking-mode/tool_choice combinations to find a working config."""
import json
import os
import urllib.error
import urllib.request

os.environ["NO_PROXY"] = "localhost,127.0.0.1"

KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not KEY:
    raise SystemExit("set DEEPSEEK_API_KEY")
BASE = "https://api.deepseek.com"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_flag",
        "description": "Return the flag",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
}]


def post(payload, path="/chat/completions"):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)


def brief(res):
    status, data = res
    if isinstance(data, str):
        return f"{status} {data[:300]}"
    msg = data["choices"][0]["message"]
    tc = msg.get("tool_calls")
    return f"{status} content={msg.get('content')!r} tool_calls={[t['function']['name'] for t in tc] if tc else None} reason={data['choices'][0].get('finish_reason')}"


base = {
    "model": "deepseek-flash",
    "messages": [{"role": "user", "content": "Use get_flag for 'web1'."}],
    "tools": TOOLS,
    "max_tokens": 200,
}

print("A tool_choice required:", brief(post({**base, "tool_choice": "required"})))
print("B forced function:", brief(post({**base, "tool_choice": {"type": "function", "function": {"name": "get_flag"}}})))
print("C auto:", brief(post({**base, "tool_choice": "auto"})))
print("D none:", brief(post({**base, "tool_choice": "none"})))
print("E reasoning_effort none:", brief(post({**base, "reasoning_effort": "none"})))
print("F thinking disabled:", brief(post({**base, "thinking": {"type": "disabled"}})))
print("G thinking false:", brief(post({**base, "thinking": False})))
print("H reasoning_effort minimal:", brief(post({**base, "reasoning_effort": "minimal"})))
print("I pro + required:", brief(post({**base, "model": "deepseek-v4-pro", "tool_choice": "required"})))
print("J reasoning on + required:", brief(post({**base, "reasoning_effort": "high", "tool_choice": "required"})))
print("K no thinking field + required:", brief(post({**base, "tool_choice": "required"})))
