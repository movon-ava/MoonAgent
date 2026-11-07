"""Proxy policy of the model client.

A dead local proxy (the user closed their VPN, HTTP(S)_PROXY still points at
127.0.0.1:7890) must not take every solver down at step 0. The client probes the
endpoint directly and only trusts the proxy env when a direct call fails.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import models  # noqa: E402

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    if condition:
        print(f"ok: {label}")
    else:
        failures.append(label)
        print(f"FAIL: {label}")


def trust_env_of(client) -> bool:
    return bool(getattr(client, "_trust_env", getattr(client, "trust_env", False)))


def main() -> int:
    original_reachable = models._direct_reachable
    original_mode = os.environ.get("LLM_TRUST_ENV")
    try:
        # 1) default: direct reachable -> bypass the proxy
        models._direct_reachable = lambda base_url: True  # type: ignore[assignment]
        os.environ.pop("LLM_TRUST_ENV", None)
        client = models._provider_http_client("https://api.deepseek.com")
        check(trust_env_of(client) is False, "direct reachable -> proxy env ignored")

        # 2) default: direct unreachable -> honour the proxy env
        models._direct_reachable = lambda base_url: False  # type: ignore[assignment]
        client = models._provider_http_client("https://api.deepseek.com")
        check(trust_env_of(client) is True, "direct unreachable -> proxy env honoured")

        # 3) explicit overrides win over the probe
        os.environ["LLM_TRUST_ENV"] = "0"
        client = models._provider_http_client("https://api.deepseek.com")
        check(trust_env_of(client) is False, "LLM_TRUST_ENV=0 forces direct")

        os.environ["LLM_TRUST_ENV"] = "1"
        client = models._provider_http_client("https://api.deepseek.com")
        check(trust_env_of(client) is True, "LLM_TRUST_ENV=1 forces the proxy env")

        # 4) the probe result is cached per base url
        calls: list[str] = []

        class FakeResponse:
            status_code = 200

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url, **kwargs):
                calls.append(url)
                return FakeResponse()

        original_client = models.httpx.Client
        models.httpx.Client = FakeClient  # type: ignore[assignment]
        try:
            models._DIRECT_CACHE.clear()
            original_reachable("https://a.example")
            original_reachable("https://a.example")
        finally:
            models.httpx.Client = original_client  # type: ignore[assignment]
        check(calls == ["https://a.example"], "probe runs once per base url (cached)")

        # 5) the provider really uses the helper for deepseek
        source = (ROOT / "backend" / "models.py").read_text(encoding="utf-8")
        check("_openai_provider(" in source, "models.py builds providers via the helper")
        check(
            source.count("_openai_provider(") >= 4,
            "azure / zen / deepseek / custom all use the helper",
        )
    finally:
        models._direct_reachable = original_reachable  # type: ignore[assignment]
        if original_mode is None:
            os.environ.pop("LLM_TRUST_ENV", None)
        else:
            os.environ["LLM_TRUST_ENV"] = original_mode

    if failures:
        print(f"\n{len(failures)} check(s) failed")
        return 1
    print("\nALL MODEL-PROXY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
