"""Check the config-form guards: per-platform validation and bogus-secret repair.

Run: uv run python scripts/test_webui_config.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import webui  # noqa: E402

CHECKS = 0


def check(label: str, ok: bool) -> None:
    global CHECKS
    CHECKS += 1
    if ok:
        print(f"  {label} ok")
    else:
        print(f"  {label} FAILED")
        raise SystemExit(1)


def expect_ok(label: str, payload: dict) -> None:
    try:
        webui._validate_payload(payload)
    except ValueError as exc:
        print(f"  {label} FAILED: unexpected rejection ({exc})")
        raise SystemExit(1) from exc
    check(label, True)


def expect_rejected(label: str, payload: dict) -> None:
    try:
        webui._validate_payload(payload)
    except ValueError:
        check(label, True)
        return
    print(f"  {label} FAILED: payload was accepted")
    raise SystemExit(1)


def main() -> None:
    url = "http://150.242.245.152:28083/1/competePlayerConsole/3/doc"

    # The reported bug: CTF+ selected, a stale DASCTF value in the payload.
    expect_ok("ctfplus ignores dasctf field", {"platform": "ctfplus", "dasctf_access_key": url})
    expect_ok("auto ignores dasctf field", {"platform": "auto", "dasctf_access_key": url})
    expect_ok("ret2shell ignores dasctf field", {"platform": "ret2shell", "dasctf_access_key": "nope"})

    # DASCTF still rejects a URL pasted into the key box.
    expect_rejected("dasctf rejects a url", {"platform": "dasctf", "dasctf_access_key": url})
    expect_rejected("dasctf rejects junk", {"platform": "dasctf", "dasctf_access_key": "s3cr3t"})

    # Masked echoes and blank values are not validated.
    expect_ok("dasctf accepts blank", {"platform": "dasctf", "dasctf_access_key": ""})
    expect_ok("dasctf accepts masked", {"platform": "dasctf", "dasctf_access_key": "ak_l••••••GPoZ"})
    expect_ok("dasctf accepts real key", {"platform": "dasctf", "dasctf_access_key": "ak_live_abc123"})

    # Bogus secrets already in .env are cleared on startup.
    with tempfile.TemporaryDirectory() as tmp:
        env = Path(tmp) / ".env"
        env.write_text(
            "PLATFORM=dasctf\n"
            f"DASCTF_ACCESS_KEY={url}\n"
            "DASCTF_URL=http://150.242.245.152:28083/\n"
            "DEEPSEEK_API_KEY=sk-real\n",
            encoding="utf-8",
        )
        original = webui.ENV_FILE
        webui.ENV_FILE = env
        try:
            webui._scrub_bogus_secrets()
            text = env.read_text(encoding="utf-8")
        finally:
            webui.ENV_FILE = original
        check("scrub cleared the key", "DASCTF_ACCESS_KEY=\n" in text)
        check("scrub kept the url", "DASCTF_URL=http://150.242.245.152:28083/" in text)
        check("scrub kept other secrets", "DEEPSEEK_API_KEY=sk-real" in text)

    print(f"ALL WEBUI-CONFIG CHECKS PASSED ({CHECKS} checks)")


if __name__ == "__main__":
    main()
