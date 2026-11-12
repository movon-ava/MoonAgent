"""Turn one solver trace into a draft chain you can finish by hand.

    uv run python scripts/harvest_chain.py logs/trace-RE6-....jsonl
    uv run python scripts/harvest_chain.py --latest 3 --status solved

The draft keeps the *sequence* (which is the part you forget) and leaves the
judgement parts empty on purpose: 判据/失败分支 must come from a human reading
the trace, otherwise the chain teaches the model the wrong lesson.  Drafts land
in ``chains/_drafts/`` and are ignored by the prompt/selector until you move
them out of that folder and fill in the blanks.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOGS = ROOT / "logs"
DRAFT_DIR = ROOT / "chains" / "_drafts"

BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("侦察", ("ls ", "ls -", "file ", "strings", "checksec", "readelf", "xxd", "find ", "unzip", "7z ", "cat ")),
    ("静态分析", ("objdump", "r2 ", "radare2", "ghidra", "gdb", "dis ", "analyze", "rabin2", "nm ", "nm-", "capstone", "ida")),
    ("编写利用/脚本", ("python", "pwntools", "gcc ", "g++ ", "make", "nasm", "unicorn", "sage", "z3")),
    ("验证与提交", ("submit_flag", "run ", "nc ", "curl", "wget", "sha256", "md5")),
)


@dataclass
class Stage:
    title: str
    tools: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)


def _bucket(text: str) -> str:
    low = text.lower()
    for title, needles in BUCKETS:
        if any(needle in low for needle in needles):
            return title
    return "其他"


def _command_of(args: object) -> str:
    if isinstance(args, dict):
        for key in ("command", "path", "url", "name"):
            if args.get(key):
                return str(args[key])
        return json.dumps(args, ensure_ascii=False)[:160]
    try:
        parsed = json.loads(str(args or "{}"))
    except json.JSONDecodeError:
        return str(args or "")[:160]
    if isinstance(parsed, dict):
        for key in ("command", "path", "url", "name"):
            if parsed.get(key):
                return str(parsed[key])
    return str(args or "")[:160]


def parse_trace(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    meta: dict = {}
    calls: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "start":
            meta = event
        elif kind == "tool_call":
            tool = str(event.get("tool") or "")
            calls.append((tool, _command_of(event.get("args"))))
    return meta, calls


def build_stages(calls: list[tuple[str, str]]) -> list[Stage]:
    stages: list[Stage] = []
    for tool, command in calls:
        title = _bucket(f"{tool} {command}")
        if not stages or stages[-1].title != title:
            stages.append(Stage(title=title))
        stage = stages[-1]
        if tool not in stage.tools:
            stage.tools.append(tool)
        line = command.splitlines()[0].strip()
        if line and line not in stage.commands:
            stage.commands.append(line[:140])
    return stages


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "chain"


def render(meta: dict, trace_name: str, stages: list[Stage]) -> str:
    challenge = str(meta.get("challenge") or trace_name)
    category = str(meta.get("category") or "").lower()
    direction = "re"
    for key in ("pwn", "web", "misc", "crypto"):
        if key in category:
            direction = key
            break
    stage_names = [f"{index + 1}. {stage.title}" for index, stage in enumerate(stages)]
    lines = [
        "---",
        f"name: draft/{slugify(challenge)}",
        f"description: TODO 一句话说明「{challenge}」这类题的解法骨架",
        "when_to_use: TODO 进入信号（看到什么就该想起这条链）",
        f"categories: [{direction}]",
        "keywords: [TODO, TODO]",
        f"stages: [{', '.join(stage_names)}]",
        f"source: {trace_name}",
        "---",
        "",
        f"> 草稿：由 `scripts/harvest_chain.py` 从 trace 自动生成，覆盖 {len(stages)} 个阶段、{sum(len(s.commands) for s in stages)} 个动作。",
        "> 补完每个阶段的「判据」和「失败分支」后，把文件从 `chains/_drafts/` 移到 `chains/<方向>/`。",
        "",
    ]
    for index, stage in enumerate(stages, start=1):
        lines += [f"## {index}. {stage.title}", ""]
        lines.append("动作：")
        for command in stage.commands[:6]:
            lines.append(f"- `{command}`")
        lines += [
            "",
            "判据：TODO 怎么确认这一步真的成功了（能说出具体证据）",
            "",
            "失败分支：TODO 不满足判据时回到哪一步、换成什么",
            "",
        ]
    return "\n".join(lines)


def latest_traces(count: int) -> list[Path]:
    return sorted(LOGS.glob("trace-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:count]


def main() -> int:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
    count = 1
    if "--latest" in sys.argv:
        index = sys.argv.index("--latest")
        count = int(sys.argv[index + 1]) if len(sys.argv) > index + 1 else 1
        args = [p for p in args if p != str(count)]
        paths = latest_traces(count)
    else:
        paths = [Path(arg) for arg in args]
    if not paths:
        print("usage: harvest_chain.py <trace.jsonl> | --latest N")
        return 2

    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path in paths:
        if not path.exists():
            print(f"missing: {path}")
            continue
        meta, calls = parse_trace(path)
        if not calls:
            print(f"no tool calls in {path.name} - skipped")
            continue
        stages = build_stages(calls)
        target = DRAFT_DIR / f"{slugify(str(meta.get('challenge') or path.stem))}.md"
        target.write_text(render(meta, path.name, stages), encoding="utf-8")
        written.append(target)
        print(f"draft: {target}  ({len(stages)} stages, {len(calls)} tool calls)")
    if written:
        print("")
        print("下一步：补完 判据/失败分支 → 移到 chains/<方向>/ → 跑 scripts/chain_report.py 看库")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
