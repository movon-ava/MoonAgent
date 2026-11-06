"""Checks for role → model routing."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import roles


def main() -> None:
    s = SimpleNamespace(role_models="", default_models="deepseek/deepseek-flash")
    assert roles.role_models(s) == {}
    assert roles.model_for("writeup", s) == "deepseek/deepseek-flash"
    print("default ok")

    s.role_models = '{"writeup": "deepseek/deepseek-flash/low", "triage": "openrouter/qwen/qwen3-235b"}'
    mapping = roles.role_models(s)
    assert mapping["writeup"].endswith("/low")
    assert roles.model_for("writeup", s).endswith("/low")
    assert roles.model_for("triage", s).startswith("openrouter/")
    assert roles.model_for("digest", s) == "deepseek/deepseek-flash"
    print("mapping ok")

    s.role_models = "{broken"
    assert roles.role_models(s) == {}
    assert roles.model_for("writeup", s, default="x/y") == "x/y"
    print("bad json ok")

    s.role_models = '["not", "a", "map"]'
    assert roles.role_models(s) == {}
    print("wrong shape ok")

    print("ALL ROLE-ROUTING CHECKS PASSED")


if __name__ == "__main__":
    main()
