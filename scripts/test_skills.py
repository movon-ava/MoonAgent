"""Self-check for the skills catalogue (backend/skills.py + use_skill tool)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import skills  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.prompts import ChallengeMeta, build_prompt  # noqa: E402
from backend.tools.skill_tool import use_skill  # noqa: E402

CHECKS = 0


def check(condition: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise SystemExit(f"FAIL: {label}")
    print(f"ok: {label}")


def main() -> None:
    folder = skills.resolve_dir("skills")
    items = skills.catalog(folder)
    check(len(items) >= 10, f"catalogue has {len(items)} skills")
    check(len({s.name for s in items}) == len(items), "skill names are unique")

    expected = {
        "pwn/format-string",
        "pwn/ret2libc-leak",
        "pwn/heap-tcache",
        "web/ssti",
        "web/jwt-bypass",
        "web/php-deserialization",
        "re/upx-unpack",
        "re/pyc-and-dotnet",
        "crypto/rsa-classic",
        "misc/stego-and-zip",
    }
    check(expected <= {s.name for s in items}, "all expected skills present")

    fmt = next(s for s in items if s.name == "pwn/format-string")
    check("fmtstr_payload" in fmt.body, "format-string body has the payload helper")
    check(bool(fmt.description) and bool(fmt.when_to_use), "frontmatter fields parsed")
    check(fmt.categories == ("pwn",), "categories parsed as a tuple")
    check("fmtstr" in fmt.keywords, "keywords parsed")

    index = skills.index_text("pwn")
    check("pwn/format-string" in index, "index lists pwn skills")
    check(len(index) <= skills.INDEX_CHARS, "index respects the size budget")
    check(index.splitlines()[0].startswith("- `pwn/"), "same-category skills come first")

    ranked = skills.match("crypto", "我们拿到了 n e c 三组 RSA", limit=2)
    check(bool(ranked) and ranked[0].name == "crypto/rsa-classic", "match ranks by category")

    check(skills.body("web/ssti", folder) is not None, "body() returns text")
    check(skills.body("nope/nothing", folder) is None, "body() is None for unknown")

    settings = Settings(_env_file=None)
    ctx = SimpleNamespace(deps=SimpleNamespace(settings=settings, challenge_name="demo"))

    loaded = asyncio.run(use_skill(ctx, "web/ssti"))
    check("{{7*7}}" in loaded, "use_skill returns the body")
    missing = asyncio.run(use_skill(ctx, "does/not-exist"))
    check("Unknown skill" in missing and "web/ssti" in missing, "use_skill lists alternatives")

    disabled = asyncio.run(use_skill(SimpleNamespace(
        deps=SimpleNamespace(settings=Settings(_env_file=None, skills_dir="no-such-dir"), challenge_name="demo")
    ), "web/ssti"))
    check("Unknown skill" in disabled and "(none installed)" in disabled, "empty dir degrades cleanly")

    prompt = build_prompt(ChallengeMeta(name="x", category="pwn"), [], skills_index=index)
    check("## 可用技能" in prompt and "pwn/format-string" in prompt, "prompt carries the index")
    plain = build_prompt(ChallengeMeta(name="x", category="pwn"), [])
    check("## 可用技能" not in plain, "prompt omits the section when disabled")

    schema = (ROOT / "backend" / "settings_schema.py").read_text(encoding="utf-8")
    check('Setting("skills_enabled", "SKILLS_ENABLED"' in schema, "schema has skills_enabled")
    check('"skills_enabled"' in schema, "panel exposes skills_enabled")

    cli = (ROOT / "backend" / "cli.py").read_text(encoding="utf-8")
    check('"--skills/--no-skills"' in cli, "cli has --skills/--no-skills")
    check("settings.skills_enabled = bool(skills_enabled)" in cli, "cli applies the flag")

    assets = (ROOT / "scripts" / "webui_assets.py").read_text(encoding="utf-8")
    check('id="skills_enabled"' in assets, "panel has the checkbox")

    solver = (ROOT / "backend" / "agents" / "solver.py").read_text(encoding="utf-8")
    check("tools.append(use_skill)" in solver, "solver registers use_skill")
    check("skills.index_text(" in solver, "solver injects the index")

    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    check("SKILLS_ENABLED=1" in env and "SKILLS_DIR=skills" in env, ".env.example documents skills")

    print(f"ALL SKILLS CHECKS PASSED ({CHECKS} checks)")


if __name__ == "__main__":
    main()
