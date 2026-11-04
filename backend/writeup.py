"""Writeup generation for solved challenges.

When enabled (``WRITEUP_ENABLED=1``), every challenge that yields a flag gets a
short Chinese writeup written to ``writeups/<category>/<slug>.md``. The solver
itself never sees this step: a second, cheap model pass turns the trace into a
readable report, so a failed writeup can never lose a solve.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from backend.config import Settings
from backend.prompts import ChallengeMeta

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

SYSTEM_PROMPT = (
    "你是一名资深 CTF 选手，负责把队友的解题过程整理成一份中文 Writeup。"
    "只写解题真实做过的事，不要编造未出现的步骤；命令、脚本、payload 原样保留。"
)

PROMPT_TEMPLATE = """请根据下面的题目信息与解题记录，写一份中文 Writeup（Markdown）。

要求：
1. 结构：`## 题目信息`、`## 分析`、`## 解题过程`、`## 关键代码/Payload`、`## Flag`、`## 小结`。
2. 用第一人称叙述思路：从现象到假设到验证。
3. 关键命令与脚本要完整可复现；输出过长时只保留关键几行。
4. 不要复述无关的试错细节，也不要编造记录里没有的内容。
5. 直接输出 Markdown 正文，不要加 ```markdown 包裹。

## 题目
- 名称：{name}
- 方向：{category}
- 分值：{value}
- 难度：{difficulty}
- 描述：
{description}

## 附件
{files}

## Flag
{flag}

## 解题记录（工具调用与关键输出）
{digest}
"""


def slugify(name: str) -> str:
    text = re.sub(r"[^\w.\-]+", "-", str(name or "").strip(), flags=re.UNICODE)
    text = text.strip("-._") or "challenge"
    return text[:80]


def trace_digest(path: str | Path, max_events: int = 160, max_chars: int = 9000) -> str:
    """Condense a solver trace into the lines a writeup needs."""
    if not path:
        return "(no trace)"
    p = Path(path)
    if not p.exists():
        return "(trace file missing)"
    lines: list[str] = []
    total = 0
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except Exception:  # noqa: BLE001 - traces are best effort
                    continue
                kind = ev.get("type")
                if kind == "tool_call":
                    text = f"- 调用 {ev.get('tool')}: {str(ev.get('args') or '')[:400]}"
                elif kind == "tool_result":
                    text = f"  结果: {str(ev.get('result') or '')[:300]}"
                elif kind == "thinking":
                    text = f"- 思考: {str(ev.get('text') or '')[:220]}"
                elif kind == "message":
                    text = f"- 说明: {str(ev.get('text') or '')[:220]}"
                elif kind == "flag_confirmed":
                    text = f"- 提交成功: {ev.get('flag') or ''}"
                else:
                    continue
                lines.append(text)
                total += len(text)
                if len(lines) >= max_events or total >= max_chars:
                    break
    except Exception as exc:  # noqa: BLE001
        logger.debug("trace digest failed for %s: %s", p, exc)
        return "(trace unreadable)"
    return "\n".join(lines) or "(empty trace)"


def build_prompt(meta: ChallengeMeta | None, flag: str | None, digest: str) -> str:
    if meta is None:
        name, category, value, difficulty, description = "?", "misc", 0, "", ""
        files = "(unknown)"
    else:
        name = getattr(meta, "name", "?")
        category = getattr(meta, "category", "misc") or "misc"
        value = getattr(meta, "value", 0) or 0
        difficulty = getattr(meta, "difficulty", "") or ""
        if not difficulty:
            difficulty = next(
                (t for t in (getattr(meta, "tags", []) or []) if t in ("入门", "简单", "中等", "困难")),
                "",
            )
        description = (getattr(meta, "description", "") or "").strip()
        dist = Path(getattr(meta, "challenge_dir", "") or "") / "distfiles"
        names = sorted(p.name for p in dist.glob("*")) if dist.is_dir() else []
        files = ", ".join(names) if names else "(none)"
    return PROMPT_TEMPLATE.format(
        name=name,
        category=category,
        value=value,
        difficulty=difficulty or "未标注",
        description=description or "(无)",
        files=files,
        flag=flag or "(unknown)",
        digest=digest,
    )


def render_markdown(meta: ChallengeMeta | None, flag: str | None, body: str) -> str:
    name = getattr(meta, "name", "challenge") if meta else "challenge"
    category = (getattr(meta, "category", "misc") if meta else "misc") or "misc"
    value = getattr(meta, "value", 0) if meta else 0
    difficulty = (getattr(meta, "difficulty", "") if meta else "") or ""
    when = time.strftime("%Y-%m-%d %H:%M")
    header = [
        f"# {name}",
        "",
        f"- 方向：{category}",
        f"- 分值：{value}",
        f"- 难度：{difficulty or '未标注'}",
        f"- Flag：`{flag or 'unknown'}`",
        f"- 生成时间：{when}（由 ctf-agent 自动整理）",
        "",
        "---",
        "",
    ]
    return "\n".join(header) + body.strip() + "\n"


async def _default_runner(settings: Settings, prompt: str) -> str:
    """One cheap model pass over the trace."""
    from pydantic_ai import Agent

    from backend.models import default_model_specs, resolve_model, resolve_model_settings

    specs = default_model_specs(settings)
    spec = specs[0] if specs else "deepseek/deepseek-flash"
    agent = Agent(resolve_model(spec, settings), system_prompt=SYSTEM_PROMPT)
    resp = await agent.run(prompt, model_settings=resolve_model_settings(spec))
    return str(getattr(resp, "output", "") or resp)


async def write(
    settings: Settings,
    meta: ChallengeMeta | None,
    result: Any,
    runner: Callable[[Settings, str], Awaitable[str]] | None = None,
) -> str | None:
    """Generate one writeup. Returns the file path, or None when skipped."""
    if not bool(getattr(settings, "writeup_enabled", False)):
        return None
    flag = str(getattr(result, "flag", "") or "").strip()
    if not flag:
        return None
    digest = trace_digest(getattr(result, "log_path", "") or "")
    prompt = build_prompt(meta, flag, digest)
    run = runner or _default_runner
    try:
        body = await asyncio.wait_for(run(settings, prompt), timeout=240)
    except Exception as exc:  # noqa: BLE001 - a writeup must never break a solve
        logger.warning("writeup generation failed for %s: %s", getattr(meta, "name", "?"), exc)
        return None
    if not str(body).strip():
        return None
    category = (getattr(meta, "category", "misc") if meta else "misc") or "misc"
    name = getattr(meta, "name", "challenge") if meta else "challenge"
    out_dir = Path(getattr(settings, "writeup_dir", "") or "writeups")
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir = out_dir / slugify(category)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slugify(name)}.md"
    path.write_text(render_markdown(meta, flag, str(body)), encoding="utf-8")
    logger.info("Writeup saved: %s", path)
    return str(path)
