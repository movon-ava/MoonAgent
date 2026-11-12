"""System prompt builder + ChallengeMeta."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from backend.tools.core import IMAGE_EXTS_FOR_VISION as IMAGE_EXTS


@dataclass
class ChallengeMeta:
    name: str = "Unknown"
    category: str = ""
    value: int = 0
    description: str = ""
    tags: list[str] = field(default_factory=list)
    connection_info: str = ""
    hints: list[dict[str, Any]] = field(default_factory=list)
    solves: int = 0
    has_container: bool = False
    challenge_dir: str = ""

    @classmethod
    def from_yaml(cls, path: str | Path) -> ChallengeMeta:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(
            name=data.get("name", "Unknown"),
            category=data.get("category", ""),
            value=data.get("value", 0),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            connection_info=data.get("connection_info", ""),
            hints=data.get("hints", []),
            solves=data.get("solves", 0),
            has_container=bool(data.get("has_container", False)),
            challenge_dir=str(Path(path).parent),
        )


def list_distfiles(challenge_dir: str) -> list[str]:
    dist = Path(challenge_dir) / "distfiles"
    if not dist.exists():
        return []
    return sorted(f.name for f in dist.iterdir() if f.is_file())


DEFAULT_INSTRUCTIONS_FILE = "INSTRUCTIONS.md"


def load_instructions(path: str | Path | None = None) -> str:
    """Read the user-editable platform instructions file.

    The file holds the flag format, submission rules and any per-competition
    hints; it is injected into every solver's system prompt.
    """
    candidate = Path(path) if path else Path(DEFAULT_INSTRUCTIONS_FILE)
    try:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001 - a broken file must not crash the run
        return ""
    return ""


def _rewrite_connection_info(conn: str) -> str:
    """Replace localhost/127.0.0.1 with host.docker.internal for bridge networking."""
    if not conn:
        return conn
    conn = re.sub(r"\blocalhost\b", "host.docker.internal", conn)
    conn = re.sub(r"\b127\.0\.0\.1\b", "host.docker.internal", conn)
    return conn


def build_prompt(
    meta: ChallengeMeta,
    distfile_names: list[str],
    container_arch: str = "unknown",
    has_named_tools: bool = True,
    platform_instructions: str = "",
    flag_hint: str = "",
    think_chinese: bool = True,
    prior_notes: str = "",
    knowledge: str = "",
    skills_index: str = "",
    skills_reco: str = "",
    chains_index: str = "",
    chains_reco: str = "",
) -> str:
    """Build the system prompt.

    has_named_tools: True for Pydantic AI solver (has view_image, webhook_create, etc.
    as discrete tools). False for Claude SDK (bash-only — model should use
    steghide/exiftool/curl instead). Codex has named dynamic tools so uses True.
    """
    conn_info = _rewrite_connection_info(meta.connection_info.strip())

    lines: list[str] = [
        "你是一名资深 CTF 解题专家。请始终用简体中文思考（你的 reasoning 必须是简体中文），"
        "但 shell 命令、代码、路径、flag 字符串保持原样，不要翻译。",
        "",
        "You are an expert CTF solver. Find the real flag for the challenge below.",
        "",
        "If a tool result contains a block starting with `[操作员提示 / OPERATOR HINT`,",
        "that is a live hint from the operator: treat it as authoritative and act on it immediately.",
        "",
    ]

    if conn_info:
        lines += [
            "> **FIRST ACTION REQUIRED**: Your very first tool call MUST connect to the service.",
            f"> Run: `{conn_info}` (use a heredoc or pwntools script as shown below).",
            "> Do NOT explore the sandbox filesystem first. The flag is on the service, not in the container.",
            "",
        ]

    if chains_reco:
        lines += [
            "> **先对齐解题链**: 这道题匹配到 " + chains_reco + "。",
            "> 第一个动作请调用 `use_chain(\"<上面的名字>\")` 把阶段、判据、失败分支读进来，再开始动手。",
            "> 之后严格按阶段推进：每完成一个阶段先按该阶段的「判据」自检，不满足就走「失败分支」，",
            "> 不要在同一个阶段里反复试错。",
            "",
        ]

    if skills_reco:
        lines += [
            "> **先加载技能**: 这道题匹配到 " + skills_reco + "。",
            "> 第一个动作请调用 `use_skill(\"<上面的名字>\")` 把那套步骤读进来，再开始分析；",
            "> 直接照着技能里的命令/脚本做，比自己从零试错快得多。",
            "",
        ]

    lines += [
        "## Challenge",
        f"**Name**    : {meta.name}",
        f"**Category**: {meta.category or 'Unknown'}",
        f"**Points**  : {meta.value or '?'}",
        f"**Arch**    : {container_arch}",
    ]
    if meta.tags:
        lines.append(f"**Tags**    : {', '.join(meta.tags)}")
    lines += ["", "## Description", meta.description or "_No description provided._", ""]

    if prior_notes:
        lines += [
            "## 队友之前的分析（同一道题，可能来自上一轮或另一个 solver）",
            "这些笔记是队友留下的结论与踩坑记录，可直接采信但要自己复核一遍；不要重复已经证明走不通的路线。",
            prior_notes.strip(),
            "",
        ]

    if knowledge:
        lines += [
            "## 该方向的常用套路（经验清单，按需参考，不要盲从）",
            knowledge.strip(),
            "",
        ]

    if chains_index:
        lines += [
            "## 这个方向已有的解题链（按阶段走，每阶段先验判据）",
            "下面是已经积累下来的解题链路：阶段顺序 + 进入信号。**阶段是检查点，不是建议**——",
            "每完成一个阶段，先用该阶段的「判据」自检；不满足就按「失败分支」换路，",
            "不要在同一个阶段里反复试错。完整内容（每阶段动作/判据/失败分支）用",
            "`use_chain(\"<名字>\")` 展开。",
            "",
        ]
        if chains_reco:
            lines += [f"按题目名/方向匹配，建议先展开：{chains_reco}", ""]
        lines += [chains_index.strip(), ""]

    if skills_index:
        lines += [
            "## 可用技能（先加载，再动手）",
            "下面只是索引。**如果你判断这道题属于某个技能（fmtstr、UPX 加壳、Go 混淆、",
            "SSTI、RSA 共模、LSB 隐写……），第一步就用 `use_skill(\"<名字>\")` 把它的完整",
            "步骤、命令和脚本模板读进上下文**，不要凭记忆硬试；同一技能读一次即可。",
            "",
        ]
        if skills_reco:
            lines += [f"按题目名/描述匹配，建议先加载：{skills_reco}", ""]
        lines += [skills_index.strip(), ""]

    if platform_instructions:
        lines += [
            "## Platform Rules (authoritative — overrides anything below)",
            platform_instructions.strip(),
            "",
        ]

    if conn_info:
        if re.match(r"^https?://", conn_info):
            hint = "This is a **web service**. Use `bash` with `curl`/`python3 requests`, or use `web_fetch`."
        elif conn_info.startswith("nc "):
            hint = (
                "This is a **TCP service**. Each `bash` call is a fresh process — "
                "use a heredoc to send multiple lines in one shot:\n"
                "```\n"
                f"{conn_info} <<'EOF'\ncommand1\ncommand2\nEOF\n"
                "```\n"
                "Or write a Python `socket` / `pwntools` script for stateful interaction."
            )
        else:
            hint = "Connect using the details above."
        lines += ["## Service Connection", "```", conn_info, "```", hint, ""]

    if distfile_names:
        lines.append("## Attached Files")
        for name in distfile_names:
            ext = Path(name).suffix.lower()
            is_img = ext in IMAGE_EXTS
            if is_img and has_named_tools:
                suffix = "  <- **IMAGE: call `view_image` immediately** (fix magic bytes first if corrupt)"
            elif is_img:
                suffix = "  <- **IMAGE: use `exiftool`, `steghide`, `zsteg`, `strings` via bash**"
            else:
                suffix = ""
            lines.append(f"- `/challenge/distfiles/{name}`{suffix}")
        lines.append("")

    visible_hints = [h for h in meta.hints if h.get("content")]
    if visible_hints:
        lines.append("## Hints")
        for h in visible_hints:
            lines.append(f"- {h['content']}")
        lines.append("")

    # pyghidra is always installed in the sandbox — show for RE/pwn/misc categories
    # or when distfiles contain binaries (non-text files)
    cat_lower = (meta.category or "").lower()
    if cat_lower in ("reverse", "reversing", "re", "pwn", "binary", "misc", ""):
        lines += [
            "## Binary Analysis",
            "**pyghidra** is installed for decompilation. Use it via bash:",
            "```python",
            "import pyghidra",
            "with pyghidra.open_program('/challenge/distfiles/binary') as flat_api:",
            "    listing = flat_api.currentProgram.getListing()",
            "    # Iterate functions, decompile, etc.",
            "```",
            "Also available: radare2 (`r2`), gdb, angr, capstone.",
            "",
        ]

    if has_named_tools:
        image_hint = "**Images: call `view_image` FIRST, before any other analysis.**"
        web_hint = "Web: fuzz params, check JS source, cookies, robots.txt. For XSS/SSRF: use `webhook_create`."
        submit_hint = "**Verify every candidate with `submit_flag`** before reporting."
    else:
        image_hint = "**Images: use `exiftool`, `steghide`, `zsteg`, `strings`, `xxd` via bash.**"
        web_hint = "Web: fuzz params, check JS source, cookies, robots.txt. For XSS/SSRF: use `curl` to webhook.site."
        submit_hint = "**Verify every candidate with `submit_flag '<flag>'`** (bash command) before reporting."

    lines += [
        "",
        "## Instructions",
        "**Use tools immediately. Do not describe — execute.**",
        "",
        "1. " + ("Connect to the service now." if conn_info else "Inspect distfiles now."),
        "2. Keep using tools until you have the flag.",
        "3. **Be creative and thorough** — try the obvious path, then explore further:",
        "   - Hidden files, env vars, backup files, HTTP headers, error messages, timing, encoding tricks.",
        f"   - {image_hint}",
        f"   - {web_hint}",
        (
            "   - Crypto: identify algorithm, weak keys, nonce reuse, padding oracles. "
            "For RSA: use `RsaCtfTool`, sage ECM, or `cado-nfs`."
        ),
        "   - Pwn: `stty raw -echo` before launching vulnerable binaries over nc.",
        '4. **Ignore placeholder flags** — `CTF{flag}`, `CTF{placeholder}` are not real flags.',
        f"5. {submit_hint}",
        *([f"   - {flag_hint}"] if flag_hint else []),
        "6. Once CORRECT: output `FLAG: <value>` on its own line.",
        "7. Do not guess. Do not ask. Cover maximum surface area.",
        "",
    ]
    if think_chinese:
        lines += [
            "## 思考语言 / Thinking language",
            "REMINDER: think in Simplified Chinese only (reasoning_content 必须是简体中文).",
            "Commands, code and flags stay in their original form.",
        ]

    return "\n".join(lines)
